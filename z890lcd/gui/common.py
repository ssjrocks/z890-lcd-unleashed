"""Small GTK helpers shared by the GUI pages."""
from io import BytesIO

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gdk, GLib, Gtk  # noqa: E402


def pil_to_texture(img):
    buf = BytesIO()
    img.save(buf, 'PNG')
    return Gdk.Texture.new_from_bytes(GLib.Bytes.new(buf.getvalue()))


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
.slot-card picture { border-radius: 8px; }
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
