"""Upload dialog: choose how a picture is fitted to the 720x1280 screen, preview it, send it."""
import json
import os

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gdk, Gtk  # noqa: E402

from .. import imaging  # noqa: E402
from ..protocol import JPEG_SLOTS  # noqa: E402
from .common import debounce, pil_to_texture  # noqa: E402

FITS = [('crop', 'Fill screen (crop)'), ('fit', 'Show whole picture'), ('stretch', 'Stretch')]
ROTATIONS = [0, 90, 180, 270]


class UploadDialog(Adw.Dialog):
    def __init__(self, window, path):
        super().__init__(title='Upload image', content_width=760, content_height=640)
        self.window, self.path = window, path
        self._uploading = False

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.upload_btn = Gtk.Button(label='Upload', css_classes=['suggested-action'])
        self.upload_btn.connect('clicked', self._on_upload)
        header.pack_end(self.upload_btn)
        toolbar.add_top_bar(header)

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18, margin_top=12, margin_bottom=12,
                       margin_start=18, margin_end=18)
        frame = Gtk.Box(css_classes=['lcd-frame'], valign=Gtk.Align.START)
        self.picture = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, width_request=270, height_request=480,
                                   can_shrink=True)
        frame.append(self.picture)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        left.append(frame)
        left.append(Gtk.Label(label='Preview at the panel\'s 720 × 1280 portrait shape', css_classes=['dim-label',
                                                                                                         'caption']))
        body.append(left)

        prefs = Adw.PreferencesPage(hexpand=True)
        g = Adw.PreferencesGroup(title='Fitting')
        self.fit = Adw.ComboRow(title='Mode', model=Gtk.StringList.new([f[1] for f in FITS]))
        self.fit.connect('notify::selected', self._changed)
        g.add(self.fit)
        self.zoom = self._scale_row(g, 'Zoom', 1.0, 3.0, 1.0, 0.05)
        self.fx = self._scale_row(g, 'Horizontal position', 0.0, 1.0, 0.5, 0.01)
        self.fy = self._scale_row(g, 'Vertical position', 0.0, 1.0, 0.5, 0.01)
        self.rotate = Adw.ComboRow(title='Rotate', model=Gtk.StringList.new([f'{r}°' for r in ROTATIONS]))
        self.rotate.connect('notify::selected', self._changed)
        g.add(self.rotate)
        self.bg_row = Adw.ActionRow(title='Background colour', subtitle='Used around the picture in "Show whole"')
        self.color = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False), valign=Gtk.Align.CENTER)
        rgba = Gdk.RGBA()
        rgba.parse('#000000')
        self.color.set_rgba(rgba)
        self.color.connect('notify::rgba', self._changed)
        self.bg_row.add_suffix(self.color)
        g.add(self.bg_row)
        prefs.add(g)

        g2 = Adw.PreferencesGroup(title='Saving')
        self.name = Adw.EntryRow(title='Name', text=os.path.splitext(os.path.basename(path))[0])
        g2.add(self.name)
        used = set(window.state.get('storage', {}).get('jpeg_slots', []))
        names = window.state.get('config', {}).get('images', {})
        free = [s for s in range(JPEG_SLOTS) if s not in used]
        slot_labels = [f'Next free slot ({free[0] + 1})' if free else 'No free slot - pick one to replace']
        for s in range(JPEG_SLOTS):
            n = names.get(str(s), {}).get('name')
            slot_labels.append(f'Slot {s + 1}' + (f' - replace "{n}"' if n else ' (empty)'))
        self.slot = Adw.ComboRow(title='Slot', model=Gtk.StringList.new(slot_labels))
        if not free:
            self.slot.set_selected(1)
        g2.add(self.slot)
        self.show_after = Adw.SwitchRow(title='Show on the LCD after uploading', active=True)
        g2.add(self.show_after)
        prefs.add(g2)

        self.progress = Gtk.ProgressBar(visible=False, show_text=True, margin_top=6)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        right.append(prefs)
        right.append(self.progress)
        body.append(right)
        toolbar.set_content(body)
        self.set_child(toolbar)
        self._sig = window.client.proxy.connect('g-signal', self._on_signal)
        self.connect('closed', lambda *a: window.client.proxy.disconnect(self._sig))
        self._changed()

    def _scale_row(self, group, title, lo, hi, val, step):
        row = Adw.ActionRow(title=title)
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
        scale.set_value(val)
        scale.set_hexpand(True)
        scale.set_size_request(180, -1)
        scale.connect('value-changed', self._changed)
        row.add_suffix(scale)
        group.add(row)
        row.scale = scale
        return row

    def options(self):
        c = self.color.get_rgba()
        return {
            'fit': FITS[self.fit.get_selected()][0],
            'zoom': self.zoom.scale.get_value(),
            'focus_x': self.fx.scale.get_value(),
            'focus_y': self.fy.scale.get_value(),
            'rotate': ROTATIONS[self.rotate.get_selected()],
            'background': '#%02x%02x%02x' % (round(c.red * 255), round(c.green * 255), round(c.blue * 255)),
        }

    def _changed(self, *a):
        crop = self.fit.get_selected() == 0
        for row in (self.zoom, self.fx, self.fy):
            row.set_sensitive(crop)
        self.bg_row.set_sensitive(self.fit.get_selected() == 1)
        debounce(self, 'render', 120, self._render)

    def _render(self):
        try:
            o = self.options()
            img = imaging.render(self.path, o['fit'], o['focus_x'], o['focus_y'], o['zoom'], o['rotate'],
                                 o['background'])
            self.picture.set_paintable(pil_to_texture(imaging.thumbnail(img, 640)))
        except Exception as e:  # unreadable file
            self.window.toast(f'Cannot open image: {e}')
            self.close()

    def _on_signal(self, proxy, sender, name, params):
        if name == 'UploadProgress' and self._uploading:
            frac = params.unpack()[1]
            self.progress.set_fraction(frac)
            self.progress.set_text(f'Uploading… {frac * 100:.0f}%')

    def _on_upload(self, *a):
        opts = self.options()
        opts.update(name=self.name.get_text().strip(), slot=self.slot.get_selected() - 1,
                    show=self.show_after.get_active())
        self._uploading = True
        self.upload_btn.set_sensitive(False)
        self.progress.set_visible(True)
        self.progress.set_text('Preparing…')
        def done(res, err):
            self._uploading = False
            if err:
                self.upload_btn.set_sensitive(True)
                self.progress.set_visible(False)
                self.window.toast(f'Upload failed: {err}')
                return
            self.window.toast(f'Uploaded to slot {res[0] + 1}')
            self.close()
        self.window.client.call_async('UploadImage', '(ss)', (self.path, json.dumps(opts)), done, 600_000)
