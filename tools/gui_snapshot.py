"""Developer tool: open the GUI, run a scripted step, save a PNG of the window. Usage:
   python3 tools/gui_snapshot.py <out.png> [page] [step]   (step: expand-row0 | upload:<image>)"""
import sys

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Graphene', '1.0')
from gi.repository import Gio, GLib, Graphene, Gtk  # noqa: E402

sys.path.insert(0, '.')
from z890lcd.gui.app import App  # noqa: E402

out, page, step = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else 'display'), \
    (sys.argv[3] if len(sys.argv) > 3 else '')
app = App()
app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)


def snap(widget):
    w, h = widget.get_width(), widget.get_height()
    snapshot = Gtk.Snapshot()
    Gtk.WidgetPaintable.new(widget).snapshot(snapshot, w, h)
    node = snapshot.to_node()
    tex = widget.get_native().get_renderer().render_texture(node, Graphene.Rect().init(0, 0, w, h))
    tex.save_to_png(out)
    print('saved', out, w, h)


def go():
    win = app.props.active_window
    win.set_default_size(1000, 820)
    win.stack.set_visible_child_name(page)
    target = [win]
    if step == 'expand-row0':
        win.stats._row_widgets[0]['expander'].set_expanded(True)
    elif step.startswith('upload:'):
        from z890lcd.gui.upload import UploadDialog
        d = UploadDialog(win, step.split(':', 1)[1])
        d.present(win)
    GLib.timeout_add(2500, lambda: (snap(target[0]), app.quit()))
    return False


app.connect('activate', lambda a: GLib.timeout_add(1500, go))
app.run(['snap'])
