"""Low-level driver for the ROG MAXIMUS Z890 EXTREME 5" LCD (USB 0b05:1bd4).

Protocol reverse-engineered from Armoury Crate 6.5.14.0 USB captures (see docs/PROTOCOL.md):
  * HID interface 1, 65-byte reports: report ID 0xEC = command/response, 0xEE = async status
  * Bulk endpoint 0x02 on interface 0 carries uploaded file data (raw JPEG)
"""
import os
import struct
import time

from .transport import NotFound, TransportError, open_transport, usb_backend

VID, PID = 0x0B05, 0x1BD4
WIDTH, HEIGHT = 720, 1280

TYPE_IMAGE, TYPE_ANIM, TYPE_BLANK, TYPE_HWMON, TYPE_WARNING = 0x11, 0x14, 0x20, 0x21, 0x23
STORE_BUILTIN, STORE_USER = 0x00, 0x01
FILE_GIF, FILE_JPEG = 0x00, 0x01
JPEG_SLOTS = 8

# Built-in wallpapers, numbered as in Armoury Crate. The panel also accepts animation indexes 2 and 3,
# but on screen they look the same as 0 and 1, so they aren't offered separately.
PRESETS = {
    1: ('Neon ROG animation', TYPE_ANIM, 0),
    2: ('Starfield ROG animation', TYPE_ANIM, 1),
    3: ('ROG wallpaper 1', TYPE_IMAGE, 0),
    4: ('ROG wallpaper 2', TYPE_IMAGE, 1),
    5: ('ROG wallpaper 3', TYPE_IMAGE, 2),
    6: ('ROG wallpaper 4', TYPE_IMAGE, 3),
    7: ('ROG wallpaper 5', TYPE_IMAGE, 4),
    8: ('ROG wallpaper 6', TYPE_IMAGE, 5),
}

# The panel font draws these code points as unit symbols
UNIT_GLYPHS = {'°C': '℃', 'V': '↊', 'RPM': '↌', 'GHz': '㎓'}

# Power block: bytes after "EC 5C"; offset 0 is the read/write flag
_B0, _B1, _DISPLAY, _W1, _B5, _STANDBY, _W2 = 3, 7, 8, 10, 13, 14, 16
_ON = 0x14  # display "on" marker (also the animation type of the standby wallpaper)


class LCDError(Exception):
    pass


class DeviceNotFound(LCDError):
    pass


class LCD:
    """One open connection to the panel. Not thread-safe; use from one thread."""

    def __init__(self, verbose=False):
        self.verbose = verbose
        try:
            self.hid = open_transport(VID, PID)
        except NotFound as e:
            raise DeviceNotFound(str(e)) from e
        except TransportError as e:
            raise LCDError(str(e)) from e
        self.path = self.hid.path
        self._usb = None

    def close(self):
        self.hid.close()
        if self._usb is not None:
            try:
                import usb.util
                usb.util.release_interface(self._usb, 0)
                usb.util.dispose_resources(self._usb)
            except Exception:
                pass
            self._usb = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---- transport ----
    def _read(self, timeout):
        data = self.hid.read(timeout)
        if data is None:
            return None
        if self.verbose:
            print('  <-', data.rstrip(b'\0').hex(' '))
        return data

    def cmd(self, *payload, timeout=1.0):
        """Send EC <payload>; return the panel's reply (bytes after EC <id>)."""
        pkt = bytes([0xEC, *payload])
        if self.verbose:
            print('  ->', pkt.hex(' '))
        self.hid.write(pkt + bytes(65 - len(pkt)))
        want = {0x82: 0x02, 0xDC: 0x5C, 0xF1: 0x71}.get(payload[0], payload[0])  # read cmds reply with another id
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            data = self._read(end - time.monotonic())
            if data and data[0] == 0xEC and data[1] == want:
                return data[2:]
        raise LCDError(f'no reply to {pkt.hex(" ")}')

    def wait_status(self, *prefix, timeout=10.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            data = self._read(end - time.monotonic())
            if data and data[0] == 0xEE and tuple(data[1:1 + len(prefix)]) == prefix:
                return data[1:]
        raise LCDError(f'no EE {bytes(prefix).hex(" ")} status from panel')

    # ---- information ----
    def firmware(self):
        return self.cmd(0x82).strip(b'\0').decode('ascii', 'replace')

    def power_block(self):
        return bytearray(self.cmd(0xDC)[:17])

    def write_power_block(self, blk):
        blk = bytearray(blk)
        blk[0] = 0x01
        self.cmd(0x5C, *blk)

    def storage(self):
        """Free space and used slots. Total/free are in KB."""
        self.cmd(0x71, 0x01, 0x01)
        try:
            self.wait_status(0x12, timeout=2)
        except LCDError:
            pass
        r = self.cmd(0xF1)
        total, free = struct.unpack_from('<II', r, 2)
        return {
            'total_kb': total,
            'free_kb': free,
            'jpeg_slots': [i for i in range(8) if r[16] >> i & 1],
            'gif_slots': [i for i in range(8) if r[11] >> i & 1],
        }

    def settings(self):
        blk = self.power_block()
        return {
            'display_on': blk[_DISPLAY] != 0,
            'brightness': blk[_B0],
            'standby_on': blk[_STANDBY] == _ON,
            'standby_wallpaper': blk[_W2] + 1 if blk[_STANDBY] else blk[_W1] + 1,
        }

    # ---- settings ----
    def set_brightness(self, pct):
        pct = max(10, min(100, int(pct)))
        blk = self.power_block()
        blk[_B0] = blk[_B1] = pct
        if blk[_B5] != 0x01:  # standby display enabled: its brightness follows
            blk[_B5] = pct
        self.write_power_block(blk)

    def set_power(self, display_on, brightness, standby_on, standby_wallpaper):
        """Write the whole power block from scratch (all values the firmware understands)."""
        b = max(10, min(100, int(brightness)))
        w = 1 if standby_wallpaper == 2 else 0
        blk = bytearray(17)
        blk[_B0] = blk[_B1] = b
        if display_on:
            blk[_DISPLAY] = _ON
            blk[_W1] = w
        if standby_on:
            blk[_B5] = b
            if display_on:
                blk[_STANDBY] = _ON
                blk[_W2] = w
        else:
            blk[_B5] = 0x01
        self.write_power_block(blk)

    # ---- what is shown ----
    def show(self, typ, store=STORE_BUILTIN, index=0):
        reply = self.cmd(0x51, typ, store, index).rstrip(b'\0')
        if reply:
            raise LCDError(f'panel rejected display {typ:02x} {store:02x} {index:02x} (code {reply.hex()})')

    def show_preset(self, n):
        _, typ, idx = PRESETS[n]
        self.show(typ, STORE_BUILTIN, idx)

    def show_image(self, slot):
        self.show(TYPE_IMAGE, STORE_USER, slot)

    def show_warning(self):
        self.show(TYPE_WARNING, STORE_USER, 0)

    # ---- hardware monitor ----
    def hwmon_layout(self, rows, theme):
        """theme 1-4; rows 1-3 (theme 1-3) or 1-5 (theme 4)."""
        self.cmd(0x52, 0x00, rows - 1, 0x00, theme - 1)
        self.cmd(0x51, TYPE_HWMON)

    def hwmon_row(self, slot, label, value):
        lab = label.encode()[:17]
        while True:  # don't cut a UTF-8 character in half
            try:
                lab.decode()
                break
            except UnicodeDecodeError:
                lab = lab[:-1]
        val = value.encode()[:41]
        self.cmd(0x53, slot, *lab.ljust(18, b'\0'), *val)

    # ---- uploads ----
    def _bulk(self):
        if self._usb is None:
            import usb.core
            import usb.util
            dev = usb.core.find(idVendor=VID, idProduct=PID, backend=usb_backend())
            if dev is None:
                raise DeviceNotFound('USB device vanished')
            try:
                if dev.is_kernel_driver_active(0):
                    dev.detach_kernel_driver(0)
            except (NotImplementedError, usb.core.USBError):
                pass
            try:
                usb.util.claim_interface(dev, 0)
            except usb.core.USBError as e:
                if os.name == 'nt':
                    raise LCDError('image uploads need the WinUSB driver on the LCD\'s "Interface 0" '
                                   '(install it with Zadig, see the README)') from e
                raise
            self._usb = dev
        return self._usb

    def upload_jpeg(self, data, slot, progress=None):
        """Store raw JPEG bytes (720x1280) in a user slot 0-7."""
        if not 0 <= slot < JPEG_SLOTS:
            raise LCDError(f'slot must be 0-{JPEG_SLOTS - 1}')
        dev = self._bulk()
        info = self.storage()
        if len(data) > info['free_kb'] * 1024:
            raise LCDError(f'image is {len(data) // 1024} KB but only {info["free_kb"]} KB is free')
        if slot in info['jpeg_slots']:
            self.delete_jpeg(slot)
        self.cmd(0x72, 0x01, FILE_JPEG, slot)
        self.cmd(0x73, 0x01)
        self.wait_status(0x13, 0x00, 0x01)
        size = struct.pack('<I', len(data)).rstrip(b'\0') or b'\0'
        self.cmd(0x7F, 0x02, *size)
        for off in range(0, len(data), 4096):
            chunk = data[off:off + 4096]
            dev.write(0x02, chunk + bytes(4096 - len(chunk)), timeout=5000)
            self.wait_status(0x14, timeout=10)
            if progress:
                progress(min(off + 4096, len(data)) / len(data))
        self.cmd(0x73, 0xFF)
        self.wait_status(0x13, 0x00, 0xFF, timeout=30)

    def delete_jpeg(self, slot):
        self.cmd(0x72, 0x01, FILE_JPEG, slot)
        self.cmd(0x73, 0x03)
        self.wait_status(0x13, 0x00, 0x03)

    def delete_gif(self, slot):
        self.cmd(0x72, 0x01, FILE_GIF, slot)
        self.cmd(0x73, 0x03)
        self.wait_status(0x13, 0x00, 0x03)

    def erase_all(self):
        self.show_preset(1)
        self.cmd(0x70, 0x5A, 0x01)
        self.cmd(0x70, 0xA5, 0x01)
