"""Communication between the GUI/CLI and the background service.

Linux:   D-Bus session bus (io.github.ssjrocks.Z890Lcd), so the service can be started on demand.
Windows: newline-delimited JSON over TCP on 127.0.0.1, authenticated with a per-user token file.
         (Z890LCD_IPC=socket selects this transport on Linux too, for testing.)

Every method takes and returns plain Python values; the transports do the encoding.
"""
import json
import os
import secrets
import socket
import subprocess
import sys
import time

import gi

gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib  # noqa: E402

from .config import CONFIG_DIR  # noqa: E402

BUS_NAME = 'io.github.ssjrocks.Z890Lcd'
OBJECT_PATH = '/io/github/ssjrocks/Z890Lcd'
INTERFACE = 'io.github.ssjrocks.Z890Lcd1'
SOCKET_PORT = int(os.environ.get('Z890LCD_PORT', '47890'))
TOKEN_FILE = os.path.join(CONFIG_DIR, 'ipc-token')

INTROSPECTION = f"""
<node>
  <interface name="{INTERFACE}">
    <method name="GetState"><arg type="s" direction="out"/></method>
    <method name="SetConfig"><arg type="s" name="changes" direction="in"/><arg type="s" direction="out"/></method>
    <method name="UploadImage">
      <arg type="s" name="path" direction="in"/><arg type="s" name="options" direction="in"/>
      <arg type="i" name="slot" direction="out"/>
    </method>
    <method name="DeleteImage"><arg type="i" name="slot" direction="in"/></method>
    <method name="ListSources"><arg type="s" direction="out"/></method>
    <method name="PreviewRows"><arg type="s" name="rows" direction="in"/><arg type="s" direction="out"/></method>
    <method name="Reconnect"><arg type="s" direction="out"/></method>
    <signal name="StateChanged"><arg type="s"/></signal>
    <signal name="UploadProgress"><arg type="i" name="slot"/><arg type="d" name="fraction"/></signal>
  </interface>
</node>
"""

# method -> (D-Bus input signature, how args are packed, D-Bus output kind)
_DBUS = {
    'GetState': (None, None, 'json'),
    'SetConfig': ('(s)', lambda a: (json.dumps(a[0]),), 'json'),
    'UploadImage': ('(ss)', lambda a: (a[0], json.dumps(a[1])), 'int'),
    'DeleteImage': ('(i)', lambda a: (a[0],), 'none'),
    'ListSources': (None, None, 'json'),
    'PreviewRows': ('(s)', lambda a: (json.dumps(a[0]),), 'json'),
    'Reconnect': (None, None, 'json'),
}
_DBUS_OUT_SIG = {'json': '(s)', 'int': '(i)', 'none': None}
LONG_CALLS = {'UploadImage': 600}  # seconds


def use_socket():
    return os.name == 'nt' or os.environ.get('Z890LCD_IPC') == 'socket'


class ServiceError(Exception):
    pass


# ======================================================================================== server side
class DBusFrontend:
    def __init__(self, dispatch, on_lost):
        self.dispatch, self.conn = dispatch, None
        self.owner = Gio.bus_own_name(Gio.BusType.SESSION, BUS_NAME, Gio.BusNameOwnerFlags.NONE,
                                      self._on_bus, None, lambda *a: on_lost())

    def _on_bus(self, conn, name):
        self.conn = conn
        node = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION)
        conn.register_object(OBJECT_PATH, node.interfaces[0], self._on_call, None, None)

    def _on_call(self, conn, sender, path, iface, method, params, invocation):
        try:
            if method not in _DBUS:
                raise ServiceError(f'unknown method {method}')
            raw = params.unpack() if params is not None else ()
            args = {'SetConfig': lambda: [json.loads(raw[0])],
                    'UploadImage': lambda: [raw[0], json.loads(raw[1] or '{}')],
                    'PreviewRows': lambda: [json.loads(raw[0])]}.get(method, lambda: list(raw))()
            result = self.dispatch(method, args)
            kind = _DBUS[method][2]
            out = {'json': lambda: GLib.Variant('(s)', (json.dumps(result),)),
                   'int': lambda: GLib.Variant('(i)', (int(result),)),
                   'none': lambda: None}[kind]()
            invocation.return_value(out)
        except Exception as e:
            invocation.return_dbus_error(f'{BUS_NAME}.Error', str(e))

    def emit(self, name, args):
        if not self.conn:
            return
        v = GLib.Variant('(s)', (json.dumps(args[0]),)) if name == 'StateChanged' else GLib.Variant('(id)', tuple(args))
        self.conn.emit_signal(None, OBJECT_PATH, INTERFACE, name, v)

    def close(self):
        Gio.bus_unown_name(self.owner)


def _load_token(create=False):
    try:
        with open(TOKEN_FILE) as f:
            return f.read().strip()
    except OSError:
        if not create:
            return ''
    os.makedirs(CONFIG_DIR, exist_ok=True)
    token = secrets.token_hex(16)
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(token)
    return token


class _SocketConn:
    def __init__(self, server, conn):
        self.server, self.conn, self.authed = server, conn, False
        self.out = conn.get_output_stream()
        self.inp = Gio.DataInputStream.new(conn.get_input_stream())
        self._next()

    def _next(self):
        self.inp.read_line_async(GLib.PRIORITY_DEFAULT, None, self._on_line)

    def _on_line(self, stream, res):
        try:
            line, _ = stream.read_line_finish_utf8(res)
        except GLib.Error:
            line = None
        if line is None:
            self.close()
            return
        try:
            msg = json.loads(line)
        except ValueError:
            self.close()
            return
        if not secrets.compare_digest(str(msg.get('token', '')), self.server.token):
            self.send({'id': msg.get('id'), 'error': 'not authorised'})
            self.close()
            return
        self.authed = True
        reply = {'id': msg.get('id')}
        try:
            reply['result'] = self.server.dispatch(msg.get('method'), msg.get('args') or [])
        except Exception as e:
            reply['error'] = str(e)
        self.send(reply)
        self._next()

    def send(self, obj):
        try:
            self.out.write_all((json.dumps(obj) + '\n').encode(), None)
        except GLib.Error:
            self.close()

    def close(self):
        self.server.clients.discard(self)
        try:
            self.conn.close(None)
        except GLib.Error:
            pass


class SocketFrontend:
    def __init__(self, dispatch, on_lost):
        self.dispatch, self.clients = dispatch, set()
        self.token = _load_token(create=True)
        self.srv = Gio.SocketService()
        try:
            addr = Gio.InetSocketAddress.new_from_string('127.0.0.1', SOCKET_PORT)
            self.srv.add_address(addr, Gio.SocketType.STREAM, Gio.SocketProtocol.TCP, None)
        except GLib.Error:
            on_lost()  # port taken: another service is running
            return
        self.srv.connect('incoming', lambda srv, conn, src: (self.clients.add(_SocketConn(self, conn)), True)[1])
        self.srv.start()

    def emit(self, name, args):
        for c in list(self.clients):
            if c.authed:
                c.send({'signal': name, 'args': args})

    def close(self):
        self.srv.stop()


def serve(dispatch, on_lost):
    return SocketFrontend(dispatch, on_lost) if use_socket() else DBusFrontend(dispatch, on_lost)


# ======================================================================================== client side
class _BaseClient:
    def state(self):
        return self.call('GetState')

    def set_config(self, **changes):
        return self.call('SetConfig', changes)

    def upload(self, path, **opts):
        return self.call('UploadImage', path, opts)

    def delete(self, slot):
        self.call('DeleteImage', slot)

    def sources(self):
        return self.call('ListSources')

    def preview_rows(self, rows):
        return self.call('PreviewRows', rows)

    def reconnect(self):
        return self.call('Reconnect')


class DBusClient(_BaseClient):
    def __init__(self):
        self.proxy = Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SESSION, Gio.DBusProxyFlags.NONE, None, BUS_NAME, OBJECT_PATH, INTERFACE, None)

    @staticmethod
    def _decode(method, res):
        kind = _DBUS[method][2]
        if kind == 'json':
            return json.loads(res.unpack()[0])
        if kind == 'int':
            return res.unpack()[0]
        return None

    @staticmethod
    def _params(method, args):
        sig, pack, _ = _DBUS[method]
        return GLib.Variant(sig, pack(args)) if sig else None

    @staticmethod
    def _msg(e):
        return e.message.split(': ', 1)[-1] if 'GDBus.Error:' in e.message else e.message

    def call(self, method, *args):
        try:
            res = self.proxy.call_sync(method, self._params(method, args), Gio.DBusCallFlags.NONE,
                                       LONG_CALLS.get(method, 120) * 1000, None)
        except GLib.Error as e:
            raise ServiceError(self._msg(e)) from None
        return self._decode(method, res)

    def call_async(self, method, args, callback):
        def done(proxy, task):
            try:
                callback(self._decode(method, proxy.call_finish(task)), None)
            except GLib.Error as e:
                callback(None, self._msg(e))
        self.proxy.call(method, self._params(method, list(args)), Gio.DBusCallFlags.NONE,
                        LONG_CALLS.get(method, 120) * 1000, None, done)

    def on_signal(self, callback):
        def handler(p, sender, name, params):
            v = params.unpack()
            callback(name, [json.loads(v[0])] if name == 'StateChanged' else list(v))
        return self.proxy.connect('g-signal', handler)

    def off_signal(self, handle):
        self.proxy.disconnect(handle)


class SocketClient(_BaseClient):
    """Sync calls use a short-lived socket each; async calls and signals share one GLib connection."""

    def __init__(self):
        self.token = _load_token()
        self._ensure_service()
        self._conn = None
        self._pending, self._handlers, self._next_id = {}, {}, 0

    # ---- start the service if it isn't running (there's no D-Bus activation on Windows)
    def _ensure_service(self):
        try:
            socket.create_connection(('127.0.0.1', SOCKET_PORT), timeout=1).close()
            self.token = _load_token()
            return
        except OSError:
            pass
        start_service()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            time.sleep(0.3)
            try:
                socket.create_connection(('127.0.0.1', SOCKET_PORT), timeout=1).close()
                self.token = _load_token()
                return
            except OSError:
                continue
        raise ServiceError('the Z890 LCD background service did not start')

    def call(self, method, *args):
        try:
            with socket.create_connection(('127.0.0.1', SOCKET_PORT), timeout=LONG_CALLS.get(method, 120)) as s:
                s.sendall((json.dumps({'id': 1, 'token': self.token, 'method': method, 'args': list(args)})
                           + '\n').encode())
                f = s.makefile('r', encoding='utf-8')
                while True:
                    line = f.readline()
                    if not line:
                        raise ServiceError('connection to the service was closed')
                    msg = json.loads(line)
                    if msg.get('id') == 1:
                        break
        except OSError as e:
            raise ServiceError(f'service unavailable: {e}') from None
        if 'error' in msg:
            raise ServiceError(msg['error'])
        return msg.get('result')

    # ---- async (GLib main loop)
    def _connection(self):
        if self._conn is None:
            client = Gio.SocketClient()
            self._conn = client.connect_to_host('127.0.0.1', SOCKET_PORT, None)
            self._out = self._conn.get_output_stream()
            self._inp = Gio.DataInputStream.new(self._conn.get_input_stream())
            self._inp.read_line_async(GLib.PRIORITY_DEFAULT, None, self._on_line)
            self._send({'id': 0, 'token': self.token, 'method': 'GetState', 'args': []})  # authenticate
        return self._conn

    def _send(self, obj):
        self._out.write_all((json.dumps(obj) + '\n').encode(), None)

    def _on_line(self, stream, res):
        try:
            line, _ = stream.read_line_finish_utf8(res)
        except GLib.Error:
            line = None
        if line is None:  # service went away: fail pending calls, reconnect lazily next time
            self._conn = None
            for cb in self._pending.values():
                cb(None, 'connection to the service was lost')
            self._pending.clear()
            return
        msg = json.loads(line)
        if 'signal' in msg:
            for h in list(self._handlers.values()):
                h(msg['signal'], msg.get('args') or [])
        elif msg.get('id') in self._pending:
            cb = self._pending.pop(msg['id'])
            cb(msg.get('result'), msg.get('error'))
        stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self._on_line)

    def call_async(self, method, args, callback):
        try:
            self._connection()
        except GLib.Error as e:
            callback(None, f'service unavailable: {e.message}')
            return
        self._next_id += 1
        self._pending[self._next_id] = callback
        self._send({'id': self._next_id, 'token': self.token, 'method': method, 'args': list(args)})

    def on_signal(self, callback):
        self._connection()
        self._next_id += 1
        self._handlers[self._next_id] = callback
        return self._next_id

    def off_signal(self, handle):
        self._handlers.pop(handle, None)


def start_service():
    """Launch the background service detached (Windows, or socket mode on Linux)."""
    if getattr(sys, 'frozen', False):
        exe = os.path.join(os.path.dirname(sys.executable),
                           'z890-lcd-service.exe' if os.name == 'nt' else 'z890-lcd-service')
        cmd = [exe]
    else:
        cmd = [sys.executable, '-m', 'z890lcd.service']
    kw = {'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL}
    if os.name == 'nt':
        kw['creationflags'] = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED | NEW_GROUP | NO_WINDOW
    else:
        kw['start_new_session'] = True
    subprocess.Popen(cmd, **kw)


def Client():
    return SocketClient() if use_socket() else DBusClient()
