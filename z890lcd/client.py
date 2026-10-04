"""Talk to the background service over D-Bus (it is started on demand by D-Bus activation)."""
import json

import gi

gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib  # noqa: E402

from .service import BUS_NAME, INTERFACE, OBJECT_PATH  # noqa: E402


class ServiceError(Exception):
    pass


class Client:
    def __init__(self):
        self.proxy = Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SESSION, Gio.DBusProxyFlags.NONE, None, BUS_NAME, OBJECT_PATH, INTERFACE, None)

    def _call(self, method, sig=None, args=(), timeout=120_000):
        try:
            res = self.proxy.call_sync(method, GLib.Variant(sig, args) if sig else None,
                                       Gio.DBusCallFlags.NONE, timeout, None)
        except GLib.Error as e:
            msg = e.message
            if 'GDBus.Error:' in msg:
                msg = msg.split(': ', 1)[-1]
            raise ServiceError(msg) from None
        return res.unpack() if res is not None else ()

    def call_async(self, method, sig, args, callback, timeout=120_000):
        """Non-blocking call for the GUI. callback(result_tuple, error_message)."""
        def done(proxy, task):
            try:
                res = proxy.call_finish(task)
                callback(res.unpack() if res is not None else (), None)
            except GLib.Error as e:
                callback(None, e.message.split(': ', 1)[-1] if 'GDBus.Error:' in e.message else e.message)
        self.proxy.call(method, GLib.Variant(sig, args) if sig else None, Gio.DBusCallFlags.NONE, timeout, None,
                        done)

    def state(self):
        return json.loads(self._call('GetState')[0])

    def set_config(self, **changes):
        return json.loads(self._call('SetConfig', '(s)', (json.dumps(changes),))[0])

    def upload(self, path, **opts):
        return self._call('UploadImage', '(ss)', (path, json.dumps(opts)), timeout=600_000)[0]

    def delete(self, slot):
        self._call('DeleteImage', '(i)', (slot,))

    def sources(self):
        return json.loads(self._call('ListSources')[0])

    def preview_rows(self, rows):
        return json.loads(self._call('PreviewRows', '(s)', (json.dumps(rows),))[0])

    def reconnect(self):
        return json.loads(self._call('Reconnect')[0])

    def on_signal(self, callback):
        """callback(signal_name, args_tuple)"""
        self.proxy.connect('g-signal', lambda p, sender, name, params: callback(name, params.unpack()))
