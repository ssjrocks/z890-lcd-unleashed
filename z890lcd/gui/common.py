"""Small GTK helpers shared by the GUI pages."""
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gdk, GLib, Gtk  # noqa: E402


def pil_to_texture(img):
    if img.mode not in ('RGB', 'RGBA'):
        img = img.convert('RGB')
    fmt = Gdk.MemoryFormat.R8G8B8A8 if img.mode == 'RGBA' else Gdk.MemoryFormat.R8G8B8
    stride = img.width * len(img.mode)
    return Gdk.MemoryTexture.new(img.width, img.height, fmt, GLib.Bytes.new(img.tobytes()), stride)


def debounce(widget_owner, key, ms, fn):
    """Call fn after `ms` of quiet; repeated calls with the same key restart the timer."""
    timers = widget_owner.__dict__.setdefault('_debounce', {})
    if timers.get(key):
        GLib.source_remove(timers[key])

    def fire():
        timers[key] = 0
        fn()
        return False
    timers[key] = GLib.timeout_add(ms, fire)


def string_dropdown(items, search=False):
    model = Gtk.StringList.new(items)
    dd = Gtk.DropDown(model=model)
    if search:
        dd.set_enable_search(True)
        dd.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, 'string'))
        dd.set_search_match_mode(Gtk.StringFilterMatchMode.SUBSTRING)
    dd.set_valign(Gtk.Align.CENTER)
    return dd


def source_label(src):
    return f'{src["category"]} · {src["name"]}'


CSS = b"""
.slot-card { padding: 8px; border-radius: 12px; }
.slot-card picture, .preset-thumb { border-radius: 8px; }
.slot-empty { border-radius: 8px; background: alpha(currentColor, 0.06); }
.preset-card { padding: 12px; min-width: 132px; min-height: 84px; }
.preset-card.active { outline: 3px solid @accent_color; outline-offset: -3px; }
.lcd-frame { background: #000; border-radius: 10px; padding: 6px; }
"""


def install_css():
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                              Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


class AnimatedPicture(Gtk.Picture):
    """Gtk.Picture that also plays animated GIFs (GTK 4 pictures only show the first frame)."""

    def __init__(self, path=None, size=None, **kw):
        super().__init__(**kw)
        self._frames, self._i, self._timer = [], 0, 0
        self.connect('map', lambda *a: self._start())
        self.connect('unmap', lambda *a: self._stop())
        if path:
            self.load(path, size)

    def load(self, path, size=None):
        from ..assets import load_frames
        self._stop()
        self._frames = [(pil_to_texture(img), ms) for img, ms in load_frames(path, size)] if path else []
        self._i = 0
        self.set_paintable(self._frames[0][0] if self._frames else None)
        if self.get_mapped():
            self._start()

    def _start(self):
        if len(self._frames) > 1 and not self._timer:
            self._timer = GLib.timeout_add(self._frames[self._i][1], self._tick)

    def _stop(self):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0

    def _tick(self):
        self._i = (self._i + 1) % len(self._frames)
        tex, ms = self._frames[self._i]
        self.set_paintable(tex)
        self._timer = GLib.timeout_add(ms, self._tick)
        return False
