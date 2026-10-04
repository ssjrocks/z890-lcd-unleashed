"""HID report transport for the LCD: Linux hidraw, or hidapi (Windows, macOS, or Linux as a fallback).

Both deliver whole 65-byte reports including the report ID (0xEC / 0xEE) as the first byte.
"""
import ctypes
import ctypes.util
import glob
import os
import select
import sys

HID_INTERFACE = 1  # interface 0 is the vendor-specific bulk interface used for uploads


class TransportError(Exception):
    pass


class NotFound(TransportError):
    pass


class HidrawTransport:
    name = 'hidraw'

    def __init__(self, vid, pid):
        path = None
        for dev in sorted(glob.glob('/sys/class/hidraw/hidraw*')):
            try:
                with open(os.path.join(dev, 'device/uevent')) as f:
                    uevent = f.read()
            except OSError:
                continue
            if f'HID_ID=0003:{vid:08X}:{pid:08X}' in uevent:
                path = '/dev/' + os.path.basename(dev)
                break
        if not path:
            raise NotFound('ROG motherboard LCD (0b05:1bd4) not found')
        try:
            self.fd = os.open(path, os.O_RDWR)
        except PermissionError as e:
            raise TransportError(f'no permission for {path}: install the udev rule (data/70-z890-lcd.rules)') from e
        self.path = path

    def write(self, report):
        os.write(self.fd, report)

    def read(self, timeout):
        r, _, _ = select.select([self.fd], [], [], max(0.0, timeout))
        return os.read(self.fd, 65) if r else None

    def close(self):
        try:
            os.close(self.fd)
        except OSError:
            pass


class _DeviceInfo(ctypes.Structure):
    pass


_DeviceInfo._fields_ = [
    ('path', ctypes.c_char_p),
    ('vendor_id', ctypes.c_ushort),
    ('product_id', ctypes.c_ushort),
    ('serial_number', ctypes.c_wchar_p),
    ('release_number', ctypes.c_ushort),
    ('manufacturer_string', ctypes.c_wchar_p),
    ('product_string', ctypes.c_wchar_p),
    ('usage_page', ctypes.c_ushort),
    ('usage', ctypes.c_ushort),
    ('interface_number', ctypes.c_int),
    ('next', ctypes.POINTER(_DeviceInfo)),
]

_hidapi = None


def _bundle_dirs():
    """Folders next to the program, where a frozen (PyInstaller) build keeps its DLLs."""
    dirs = [os.path.dirname(sys.executable)]
    if hasattr(sys, '_MEIPASS'):
        dirs.insert(0, sys._MEIPASS)
    return dirs


def load_hidapi():
    global _hidapi
    if _hidapi is not None:
        return _hidapi
    names = ['hidapi.dll', 'libhidapi-0.dll', 'libhidapi.dll'] if os.name == 'nt' else \
        ['libhidapi-hidraw.so.0', 'libhidapi-libusb.so.0', 'libhidapi.so', 'libhidapi.dylib']
    candidates = [os.path.join(d, n) for d in _bundle_dirs() for n in names] + names
    found = ctypes.util.find_library('hidapi')
    if found:
        candidates.append(found)
    for c in candidates:
        try:
            lib = ctypes.CDLL(c)
            break
        except OSError:
            continue
    else:
        raise TransportError('hidapi library not found')
    lib.hid_init.restype = ctypes.c_int
    lib.hid_enumerate.restype = ctypes.POINTER(_DeviceInfo)
    lib.hid_enumerate.argtypes = [ctypes.c_ushort, ctypes.c_ushort]
    lib.hid_free_enumeration.argtypes = [ctypes.POINTER(_DeviceInfo)]
    lib.hid_open_path.restype = ctypes.c_void_p
    lib.hid_open_path.argtypes = [ctypes.c_char_p]
    lib.hid_write.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
    lib.hid_read_timeout.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_int]
    lib.hid_close.argtypes = [ctypes.c_void_p]
    lib.hid_error.restype = ctypes.c_wchar_p
    lib.hid_error.argtypes = [ctypes.c_void_p]
    lib.hid_init()
    _hidapi = lib
    return lib


class HidapiTransport:
    name = 'hidapi'

    def __init__(self, vid, pid):
        lib = self.lib = load_hidapi()
        head = lib.hid_enumerate(vid, pid)
        path, node = None, head
        while node:
            if node.contents.interface_number == HID_INTERFACE:
                path = node.contents.path
                break
            node = node.contents.next
        if head:
            lib.hid_free_enumeration(head)
        if not path:
            raise NotFound('ROG motherboard LCD (0b05:1bd4) not found')
        self.dev = lib.hid_open_path(path)
        if not self.dev:
            raise TransportError(f'cannot open the LCD ({path.decode(errors="replace")}): '
                                 f'{lib.hid_error(None) or "access denied"}')
        self.path = path.decode(errors='replace')

    def write(self, report):
        n = self.lib.hid_write(self.dev, report, len(report))
        if n < 0:
            raise OSError(f'HID write failed: {self.lib.hid_error(self.dev)}')

    def read(self, timeout):
        buf = ctypes.create_string_buffer(65)
        n = self.lib.hid_read_timeout(self.dev, buf, 65, max(0, int(timeout * 1000)))
        if n < 0:
            raise OSError(f'HID read failed: {self.lib.hid_error(self.dev)}')
        return buf.raw[:n] if n else None

    def close(self):
        if self.dev:
            self.lib.hid_close(self.dev)
            self.dev = None


def open_transport(vid, pid):
    """hidraw on Linux (no extra library needed), hidapi elsewhere. Z890LCD_HID=hidapi forces hidapi."""
    if sys.platform.startswith('linux') and os.environ.get('Z890LCD_HID') != 'hidapi':
        return HidrawTransport(vid, pid)
    return HidapiTransport(vid, pid)


def usb_backend():
    """pyusb backend; on Windows/frozen builds use the bundled libusb-1.0 DLL."""
    import usb.backend.libusb1
    for d in _bundle_dirs():
        for name in ('libusb-1.0.dll', 'libusb-1.0.so.0'):
            p = os.path.join(d, name)
            if os.path.exists(p):
                return usb.backend.libusb1.get_backend(find_library=lambda _x, p=p: p)
    return None  # pyusb's default search
