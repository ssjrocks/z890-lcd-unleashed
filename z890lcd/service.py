"""Background service: owns the LCD, keeps dynamic content running, serves the API in ipc.py
(D-Bus on Linux, a local socket on Windows)."""
import logging
import os
import random
import signal
import sys

import gi

gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib  # noqa: E402

from . import __version__, config, imaging, ipc  # noqa: E402
from .protocol import JPEG_SLOTS, LCD, DeviceNotFound, LCDError  # noqa: E402
from .sensors import SensorHub  # noqa: E402

POWER_KEYS = ('display_on', 'brightness', 'standby_on', 'standby_wallpaper')
MODE_KEYS = ('mode', 'preset', 'image_slot', 'slideshow', 'hwmon')

log = logging.getLogger('z890lcd')


class Service:
    def __init__(self):
        self.cfg = config.load()
        self.sensors = SensorHub()
        self.lcd = None
        self.error = ''
        self.firmware = ''
        self.storage = {}
        self.warning_active = False
        self.showing = ''
        self._mode_timer = 0
        self._warn_timer = 0
        self._reconnect_timer = 0
        self._slide_pos = 0
        self._frontend = None
        os.makedirs(config.IMAGE_DIR, exist_ok=True)

    # ------------------------------------------------------------------ device lifecycle
    def connect(self):
        self._close()
        try:
            self.lcd = LCD()
            self.firmware = self.lcd.firmware()
            self.storage = self.lcd.storage()
            self.error = ''
            log.info('connected to LCD %s on %s', self.firmware, self.lcd.path)
            self._sync_library()
            self.apply_all()
        except (LCDError, OSError) as e:
            self._fail(e)
        self._emit_state()
        return self.lcd is not None

    def _close(self):
        if self.lcd:
            self.lcd.close()
        self.lcd = None

    def _fail(self, e):
        msg = str(e)
        if msg != self.error:
            log.warning('LCD unavailable: %s', msg)
        self.error = msg
        self._close()
        self._stop_mode_timer()
        if not self._reconnect_timer:
            self._reconnect_timer = GLib.timeout_add_seconds(3, self._try_reconnect)
        self._emit_state()

    def _try_reconnect(self):
        self._reconnect_timer = 0
        if not self.connect() and not self._reconnect_timer:
            self._reconnect_timer = GLib.timeout_add_seconds(3, self._try_reconnect)
        return False

    def _do(self, fn, *args, **kw):
        """Run a device operation; on failure drop the connection and start reconnecting."""
        if not self.lcd:
            raise LCDError(self.error or 'LCD not connected')
        try:
            return fn(*args, **kw)
        except DeviceNotFound as e:
            self._fail(e)
            raise
        except OSError as e:
            self._fail(e)
            raise LCDError(str(e)) from e

    # ------------------------------------------------------------------ applying settings
    def apply_all(self):
        c = self.cfg
        self._do(self.lcd.set_power, c['display_on'], c['brightness'], c['standby_on'], c['standby_wallpaper'])
        self.apply_mode()
        self._restart_warning_timer()

    def apply_mode(self):
        self._stop_mode_timer()
        if not self.lcd or not self.cfg['display_on']:
            self.showing = 'off'
            return
        if self.warning_active:
            self._do(self.lcd.show_warning)
            self.showing = 'warning'
            return
        mode = self.cfg['mode']
        if mode == 'image' and self.cfg['image_slot'] not in self.storage.get('jpeg_slots', []):
            mode = 'preset'
        if mode == 'slideshow' and not self._slideshow_slots():
            mode = 'preset'
        if mode == 'preset':
            self._do(self.lcd.show_preset, self.cfg['preset'])
            self.showing = f'preset {self.cfg["preset"]}'
        elif mode == 'image':
            self._do(self.lcd.show_image, self.cfg['image_slot'])
            self.showing = f'image {self.cfg["image_slot"]}'
        elif mode == 'slideshow':
            self._slide_pos = -1
            self._slideshow_tick()
            self._mode_timer = GLib.timeout_add(int(self.cfg['slideshow']['interval'] * 1000), self._slideshow_tick)
            self.showing = 'slideshow'
        elif mode == 'hwmon':
            hw = self.cfg['hwmon']
            self._do(self.lcd.hwmon_layout, len(hw['rows']), hw['theme'])
            self._hwmon_tick()
            self._mode_timer = GLib.timeout_add(int(hw['interval'] * 1000), self._hwmon_tick)
            self.showing = 'hwmon'

    def _stop_mode_timer(self):
        if self._mode_timer:
            GLib.source_remove(self._mode_timer)
            self._mode_timer = 0

    def _slideshow_slots(self):
        have = set(self.storage.get('jpeg_slots', []))
        return [s for s in self.cfg['slideshow']['slots'] if s in have]

    def _slideshow_tick(self):
        slots = self._slideshow_slots()
        if not slots or not self.lcd:
            return False
        if self.cfg['slideshow'].get('shuffle') and len(slots) > 1:
            choices = [i for i in range(len(slots)) if i != self._slide_pos]
            self._slide_pos = random.choice(choices)
        else:
            self._slide_pos = (self._slide_pos + 1) % len(slots)
        try:
            self._do(self.lcd.show_image, slots[self._slide_pos])
        except LCDError:
            return False
        return True

    def format_rows(self, rows, theme):
        out = []
        for r in rows:
            val = self.sensors.read(r['source'], r.get('param', ''))
            text, unit = self.sensors.format(r['source'], val, r.get('decimals', -1), r.get('unit'))
            out.append({'label': r['label'], 'text': text, 'unit': unit})
        return out

    def _hwmon_tick(self):
        if not self.lcd:
            return False
        hw = self.cfg['hwmon']
        try:
            for i, row in enumerate(self.format_rows(hw['rows'], hw['theme'])):
                if hw['theme'] == 4:  # theme 4 draws the unit on its own line
                    value = row['text'] + ('\n' + row['unit'] if row['unit'] else '')
                else:  # themes 1-3: Armoury Crate right-aligns with two spaces
                    value = '  ' + row['text'] + row['unit']
                self._do(self.lcd.hwmon_row, i, row['label'], value)
        except LCDError:
            return False
        return True

    # ------------------------------------------------------------------ temperature warning
    def _restart_warning_timer(self):
        if self._warn_timer:
            GLib.source_remove(self._warn_timer)
            self._warn_timer = 0
        if self.cfg['temp_warning']['enabled']:
            self._warn_timer = GLib.timeout_add_seconds(2, self._warning_tick)
        elif self.warning_active:
            self.warning_active = False
            self._safe(self.apply_mode)

    def _warning_tick(self):
        tw = self.cfg['temp_warning']
        val = self.sensors.read(tw['source'])
        if not isinstance(val, (int, float)):
            return True
        if not self.warning_active and val >= tw['threshold']:
            log.warning('temperature warning: %s = %.1f >= %.1f', tw['source'], val, tw['threshold'])
            self.warning_active = True
            self._safe(self.apply_mode)
            self._emit_state()
        elif self.warning_active and val <= tw['threshold'] - tw['hysteresis']:
            self.warning_active = False
            self._safe(self.apply_mode)
            self._emit_state()
        return True

    def _safe(self, fn, *a):
        try:
            fn(*a)
        except LCDError:
            pass

    # ------------------------------------------------------------------ image library
    def _sync_library(self):
        on_panel = set(self.storage.get('jpeg_slots', []))
        images = self.cfg['images']
        changed = False
        for slot in list(images):
            if int(slot) not in on_panel:
                del images[slot]
                changed = True
        for slot in on_panel:
            if str(slot) not in images:
                images[str(slot)] = {'name': f'Image {slot + 1} (uploaded elsewhere)', 'file': None, 'thumb': None}
                changed = True
        if changed:
            config.save(self.cfg)

    def upload(self, path, opts):
        slot = int(opts.get('slot', -1))
        if slot < 0:
            used = set(self.storage.get('jpeg_slots', []))
            free = [s for s in range(JPEG_SLOTS) if s not in used]
            if not free:
                raise LCDError('all 8 image slots are full - delete one first')
            slot = free[0]
        img = imaging.render(path, opts.get('fit', 'crop'), float(opts.get('focus_x', 0.5)),
                             float(opts.get('focus_y', 0.5)), float(opts.get('zoom', 1.0)),
                             int(opts.get('rotate', 0)), opts.get('background', '#000000'))
        data = imaging.to_jpeg(img, int(opts.get('quality', 90)))
        self._stop_mode_timer()  # don't interleave stats updates with the upload

        def progress(frac):
            self._emit('UploadProgress', [slot, frac])
            ctx = GLib.MainContext.default()
            while ctx.pending():  # let the signal go out during the blocking upload
                ctx.iteration(False)
        try:
            self._do(self.lcd.upload_jpeg, data, slot, progress)
        finally:
            self.storage = self._do(self.lcd.storage)
        base = os.path.join(config.IMAGE_DIR, f'slot{slot}')
        with open(base + '.jpg', 'wb') as f:
            f.write(data)
        imaging.thumbnail(img).save(base + '-thumb.jpg', quality=85)
        name = opts.get('name') or os.path.splitext(os.path.basename(path))[0]
        self.cfg['images'][str(slot)] = {'name': name, 'file': base + '.jpg', 'thumb': base + '-thumb.jpg'}
        if opts.get('show', True):
            self.cfg['mode'], self.cfg['image_slot'] = 'image', slot
        config.save(self.cfg)
        self.apply_mode()
        self._emit_state()
        return slot

    def delete(self, slot):
        self._stop_mode_timer()
        self._do(self.lcd.delete_jpeg, slot)
        self.storage = self._do(self.lcd.storage)
        info = self.cfg['images'].pop(str(slot), None)
        for p in (info or {}).values():
            if isinstance(p, str) and p.startswith(config.IMAGE_DIR) and os.path.exists(p):
                os.remove(p)
        self.cfg['slideshow']['slots'] = [s for s in self.cfg['slideshow']['slots'] if s != slot]
        config.save(self.cfg)
        self.apply_mode()
        self._emit_state()

    # ------------------------------------------------------------------ config changes
    def set_config(self, changes):
        old = self.cfg
        new = config.validate(config._merge(old, changes))
        new['images'] = old['images']  # only the service edits the library
        self.cfg = new
        config.save(new)
        if not self.lcd:
            self._emit_state()
            return
        power_changed = any(old[k] != new[k] for k in POWER_KEYS)
        mode_changed = any(old[k] != new[k] for k in MODE_KEYS)
        if power_changed:
            self._do(self.lcd.set_power, new['display_on'], new['brightness'], new['standby_on'],
                     new['standby_wallpaper'])
        if mode_changed or (power_changed and new['display_on'] != old['display_on']):
            self.apply_mode()
        if old['temp_warning'] != new['temp_warning']:
            self._restart_warning_timer()
        self._emit_state()

    # ------------------------------------------------------------------ D-Bus
    def state(self):
        return {
            'version': __version__,
            'connected': self.lcd is not None,
            'error': self.error,
            'firmware': self.firmware,
            'storage': self.storage,
            'showing': self.showing,
            'warning_active': self.warning_active,
            'config': self.cfg,
            'image_dir': config.IMAGE_DIR,
        }

    def _emit(self, name, args):
        if self._frontend:
            self._frontend.emit(name, args)

    def _emit_state(self):
        self._emit('StateChanged', [self.state()])

    def dispatch(self, method, args):
        """Every API call from the GUI/CLI ends up here (see ipc.py)."""
        try:
            if method == 'GetState':
                return self.state()
            if method == 'SetConfig':
                self.set_config(args[0])
                return self.state()
            if method == 'UploadImage':
                return self.upload(args[0], args[1] if len(args) > 1 else {})
            if method == 'DeleteImage':
                self.delete(int(args[0]))
                return None
            if method == 'ListSources':
                self.sensors.discover()
                return self.sensors.list()
            if method == 'PreviewRows':
                return self.format_rows(args[0], 1)
            if method == 'Reconnect':
                self.connect()
                return self.state()
            raise LCDError(f'unknown method {method}')
        except LCDError as e:
            log.warning('%s: %s', method, e)
            raise
        except Exception:
            log.exception('%s failed', method)
            raise

    def _on_sleep(self, conn, sender, path, iface, signal_name, params):
        going_to_sleep = params.unpack()[0]
        if not going_to_sleep:
            log.info('resumed from sleep, re-applying settings')
            GLib.timeout_add_seconds(3, lambda: (self.connect(), False)[1])

    def run(self):
        loop = GLib.MainLoop()

        def lost():
            log.error('another z890-lcd service is already running')
            loop.quit()
        self._frontend = ipc.serve(self.dispatch, lost)
        if sys.platform.startswith('linux'):
            try:
                system = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
                system.signal_subscribe('org.freedesktop.login1', 'org.freedesktop.login1.Manager',
                                        'PrepareForSleep', '/org/freedesktop/login1', None,
                                        Gio.DBusSignalFlags.NONE, self._on_sleep)
            except GLib.Error:
                pass
            try:
                gi.require_version('GLibUnix', '2.0')
                from gi.repository import GLibUnix
                add_signal = GLibUnix.signal_add
            except (ImportError, ValueError):
                add_signal = GLib.unix_signal_add
            for sig in (signal.SIGINT, signal.SIGTERM):
                add_signal(GLib.PRIORITY_DEFAULT, sig, loop.quit)
        self.connect()
        loop.run()
        self._frontend.close()
        self._stop_mode_timer()
        self._close()


def main():
    import warnings
    warnings.filterwarnings('ignore', category=DeprecationWarning)  # register_object: still the simplest API
    if sys.stderr is None or os.name == 'nt':  # windowed Windows build: no console, log to a file
        os.makedirs(config.DATA_DIR, exist_ok=True)
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                            filename=os.path.join(config.DATA_DIR, 'service.log'))
    else:
        logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s', stream=sys.stderr)
    Service().run()


if __name__ == '__main__':
    main()
