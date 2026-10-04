"""Main window."""
import json
import os
import subprocess
import sys

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from .. import APP_ID, __version__  # noqa: E402
from ..client import Client, ServiceError  # noqa: E402
from ..protocol import JPEG_SLOTS, PRESETS, TYPE_ANIM  # noqa: E402
from .common import debounce, install_css, source_label, string_dropdown  # noqa: E402
from .stats import StatsPage  # noqa: E402
from .upload import UploadDialog  # noqa: E402

IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp', 'image/gif', 'image/bmp', 'image/tiff']


class DisplayPage(Adw.PreferencesPage):
    def __init__(self, win):
        super().__init__()
        self.win = win
        g = Adw.PreferencesGroup(title='Screen')
        self.on = Adw.SwitchRow(title='Display on')
        self.on.connect('notify::active', lambda *a: win.loading or win.set_config(display_on=self.on.get_active()))
        g.add(self.on)
        row = Adw.ActionRow(title='Brightness')
        self.bright = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 10, 100, 1)
        self.bright.set_hexpand(True)
        self.bright.set_size_request(260, -1)
        self.bright.set_draw_value(True)
        self.bright.set_value_pos(Gtk.PositionType.RIGHT)
        self.bright.connect('value-changed', self._on_bright)
        row.add_suffix(self.bright)
        g.add(row)
        self.showing = Adw.ActionRow(title='Showing now')
        g.add(self.showing)
        self.add(g)

        g = Adw.PreferencesGroup(title='Built-in wallpapers', description='Stored on the panel')
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4, min_children_per_line=2,
                           row_spacing=10, column_spacing=10, homogeneous=True)
        self.preset_btns = {}
        for n, (name, typ, _) in PRESETS.items():
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            box.append(Gtk.Image(icon_name='media-playback-start-symbolic' if typ == TYPE_ANIM
                                 else 'image-x-generic-symbolic', pixel_size=28))
            box.append(Gtk.Label(label=f'{n}. {name}', wrap=True, justify=Gtk.Justification.CENTER,
                                 max_width_chars=14))
            b = Gtk.Button(child=box, css_classes=['card', 'preset-card'])
            b.connect('clicked', lambda *a, n=n: win.set_config(mode='preset', preset=n))
            flow.append(b)
            self.preset_btns[n] = b
        g.add(flow)
        self.add(g)

    def _on_bright(self, scale):
        if not self.win.loading:
            debounce(self, 'bright', 250, lambda: self.win.set_config(brightness=int(scale.get_value())))

    def load(self, st):
        c = st['config']
        self.on.set_active(c['display_on'])
        self.bright.set_value(c['brightness'])
        showing = st.get('showing', '')
        text = {'off': 'Display is off', 'slideshow': 'Slideshow', 'hwmon': 'Hardware monitor',
                'warning': 'Temperature warning!'}.get(showing, '')
        if showing.startswith('preset'):
            text = f'Built-in: {PRESETS[c["preset"]][0]}'
        elif showing.startswith('image'):
            text = 'Image: ' + c['images'].get(str(c['image_slot']), {}).get('name', f'slot {c["image_slot"] + 1}')
        self.showing.set_subtitle(text or '—')
        for n, b in self.preset_btns.items():
            if c['mode'] == 'preset' and c['preset'] == n:
                b.add_css_class('active')
            else:
                b.remove_css_class('active')


class ImagesPage(Adw.PreferencesPage):
    def __init__(self, win):
        super().__init__()
        self.win = win
        g = Adw.PreferencesGroup(title='My images', description='Any picture format, fitted to the 720 × 1280 screen')
        up = Gtk.Button(label='Upload…', css_classes=['suggested-action'], valign=Gtk.Align.CENTER)
        up.connect('clicked', self._choose)
        g.set_header_suffix(up)
        self.flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4,
                                min_children_per_line=2, row_spacing=12, column_spacing=12, homogeneous=True)
        g.add(self.flow)
        self.storage = Gtk.Label(css_classes=['dim-label', 'caption'], xalign=0, margin_top=8)
        g.add(self.storage)
        self.add(g)

        g = Adw.PreferencesGroup(title='Slideshow',
                                 description='Tick "Slideshow" on the images to include. The panel fades '
                                             'between pictures, so changes are limited to one every 2 s or more.')
        self.interval = Adw.SpinRow.new_with_range(2, 3600, 1)
        self.interval.set_title('Seconds per picture')
        self.interval.connect('notify::value', self._slideshow_edit)
        g.add(self.interval)
        self.shuffle = Adw.SwitchRow(title='Shuffle')
        self.shuffle.connect('notify::active', self._slideshow_edit)
        g.add(self.shuffle)
        self.start = Adw.ButtonRow(title='Start slideshow', start_icon_name='media-playback-start-symbolic')
        self.start.connect('activated', lambda *a: win.set_config(mode='slideshow'))
        g.add(self.start)
        self.add(g)
        self._cards = []

    def _slideshow_edit(self, *a):
        if self.win.loading:
            return
        debounce(self, 'ss', 400, lambda: self.win.set_config(slideshow={
            'interval': self.interval.get_value(), 'shuffle': self.shuffle.get_active()}))

    def load(self, st):
        c = st['config']
        self.interval.set_value(c['slideshow']['interval'])
        self.shuffle.set_active(c['slideshow']['shuffle'])
        for card in self._cards:
            self.flow.remove(card)
        self._cards = []
        in_show = set(c['slideshow']['slots'])
        for s in range(JPEG_SLOTS):
            info = c['images'].get(str(s))
            card = self._card(s, info, s in in_show, c['mode'] == 'image' and c['image_slot'] == s
                              and st.get('showing', '').startswith('image'))
            self.flow.append(card)
            self._cards.append(card)
        stg = st.get('storage') or {}
        if stg:
            used = len(stg.get('jpeg_slots', []))
            self.storage.set_label(f'{used} of {JPEG_SLOTS} slots used · '
                                   f'{stg["free_kb"] / 1024:.1f} MB free of {stg["total_kb"] / 1024:.1f} MB')
        self.start.set_sensitive(bool(in_show & set(stg.get('jpeg_slots', []))))

    def _card(self, slot, info, in_show, active):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=['card', 'slot-card'])
        if active:
            box.add_css_class('preset-card')
            box.add_css_class('active')
        thumb = info.get('thumb') if info else None
        if thumb and os.path.exists(thumb):
            pic = Gtk.Picture.new_for_filename(thumb)
            pic.set_content_fit(Gtk.ContentFit.COVER)
            pic.set_size_request(108, 192)
            pic.set_halign(Gtk.Align.CENTER)
            pic.set_can_shrink(True)
            box.append(pic)
        else:
            ph = Gtk.Box(css_classes=['slot-empty'], width_request=108, height_request=192,
                         halign=Gtk.Align.CENTER)
            ph.append(Gtk.Label(label='No preview' if info else 'Empty', hexpand=True, vexpand=True,
                                css_classes=['dim-label'], wrap=True, justify=Gtk.Justification.CENTER))
            box.append(ph)
        box.append(Gtk.Label(label=f'{slot + 1}. ' + (info['name'] if info else 'Empty slot'),
                             ellipsize=3, max_width_chars=16))
        if info:
            row = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
            show = Gtk.Button(label='Show', css_classes=['pill'] if not active else ['pill', 'suggested-action'])
            show.connect('clicked', lambda *a: self.win.set_config(mode='image', image_slot=slot))
            rm = Gtk.Button(icon_name='user-trash-symbolic', tooltip_text='Delete from panel',
                            css_classes=['flat', 'circular'])
            rm.connect('clicked', lambda *a: self._confirm_delete(slot, info['name']))
            row.append(show)
            row.append(rm)
            box.append(row)
            chk = Gtk.CheckButton(label='Slideshow', active=in_show, halign=Gtk.Align.CENTER)
            chk.connect('toggled', lambda b: self._toggle_slide(slot, b.get_active()))
            box.append(chk)
        else:
            b = Gtk.Button(label='Upload…', css_classes=['flat'], halign=Gtk.Align.CENTER)
            b.connect('clicked', self._choose)
            box.append(b)
        return box

    def _toggle_slide(self, slot, on):
        slots = set(self.win.state['config']['slideshow']['slots'])
        slots = slots | {slot} if on else slots - {slot}
        self.win.set_config(slideshow={'slots': sorted(slots)})

    def _confirm_delete(self, slot, name):
        d = Adw.AlertDialog(heading='Delete image?', body=f'"{name}" will be removed from slot {slot + 1} '
                                                          'on the panel.')
        d.add_response('cancel', 'Cancel')
        d.add_response('delete', 'Delete')
        d.set_response_appearance('delete', Adw.ResponseAppearance.DESTRUCTIVE)
        d.connect('response', lambda d, r: r == 'delete' and self.win.call('DeleteImage', '(i)', (slot,),
                                                                           f'Deleted slot {slot + 1}'))
        d.present(self.win)

    def _choose(self, *a):
        dlg = Gtk.FileDialog(title='Choose a picture')
        f = Gtk.FileFilter(name='Images')
        for m in IMAGE_TYPES:
            f.add_mime_type(m)
        store = Gio.ListStore.new(Gtk.FileFilter)
        store.append(f)
        dlg.set_filters(store)
        dlg.set_default_filter(f)

        def done(d, res):
            try:
                file = d.open_finish(res)
            except GLib.Error:
                return
            if file and file.get_path():
                UploadDialog(self.win, file.get_path()).present(self.win)
        dlg.open(self.win, None, done)


class SettingsPage(Adw.PreferencesPage):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self._temp_sources = []
        g = Adw.PreferencesGroup(title='When the PC is asleep or shut down')
        self.standby = Adw.SwitchRow(title='Keep the LCD on', subtitle='Shows an animation in sleep, hibernate '
                                                                       'and soft-off')
        self.standby.connect('notify::active', lambda *a: win.loading or win.set_config(
            standby_on=self.standby.get_active()))
        g.add(self.standby)
        self.wallpaper = Adw.ComboRow(title='Animation', model=Gtk.StringList.new([PRESETS[1][0], PRESETS[2][0]]))
        self.wallpaper.connect('notify::selected', lambda *a: win.loading or win.set_config(
            standby_wallpaper=self.wallpaper.get_selected() + 1))
        g.add(self.wallpaper)
        self.add(g)

        g = Adw.PreferencesGroup(title='Temperature warning',
                                 description='Switches the LCD to the panel\'s built-in warning screen while '
                                             'a sensor is too hot.')
        self.warn = Adw.SwitchRow(title='Enabled')
        self.warn.connect('notify::active', self._warn_edit)
        g.add(self.warn)
        row = Adw.ActionRow(title='Sensor')
        self.warn_src = string_dropdown([], search=True)
        self.warn_src.set_size_request(260, -1)
        self.warn_src.connect('notify::selected', self._warn_edit)
        row.add_suffix(self.warn_src)
        g.add(row)
        self.warn_thr = Adw.SpinRow.new_with_range(40, 120, 1)
        self.warn_thr.set_value(90)
        self.warn_thr.set_title('Threshold (°C)')
        self.warn_thr.connect('notify::value', self._warn_edit)
        g.add(self.warn_thr)
        self.add(g)

        g = Adw.PreferencesGroup(title='Device')
        self.dev = Adw.ActionRow(title='Panel')
        g.add(self.dev)
        self.fw = Adw.ActionRow(title='Firmware')
        g.add(self.fw)
        rc = Adw.ButtonRow(title='Reconnect', start_icon_name='view-refresh-symbolic')
        rc.connect('activated', lambda *a: win.call('Reconnect', None, (), 'Reconnected'))
        g.add(rc)
        self.add(g)

        g = Adw.PreferencesGroup(title='Background service',
                                 description='Keeps stats and slideshows running when this window is closed.')
        self.autostart = Adw.SwitchRow(title='Start at login')
        self.autostart.set_active(self._service_enabled())
        self.autostart.connect('notify::active', self._toggle_autostart)
        g.add(self.autostart)
        self.add(g)

    @staticmethod
    def _service_enabled():
        try:
            return subprocess.run(['systemctl', '--user', 'is-enabled', 'z890-lcd.service'],
                                  capture_output=True, text=True).stdout.strip() == 'enabled'
        except OSError:
            return False

    def _toggle_autostart(self, row, *a):
        verb = 'enable' if row.get_active() else 'disable'
        r = subprocess.run(['systemctl', '--user', verb, 'z890-lcd.service'], capture_output=True, text=True)
        if r.returncode:
            self.win.toast(f'Could not {verb} the service: {r.stderr.strip()}')

    def load_sources(self, sources):
        self._temp_sources = [s for s in sources if s['category'] == 'Temperature']
        loading, self.win.loading = self.win.loading, True  # filling the list must not count as an edit
        try:
            self.warn_src.set_model(Gtk.StringList.new([source_label(s) for s in self._temp_sources]))
        finally:
            self.win.loading = loading

    def _warn_edit(self, *a):
        if self.win.loading:
            return
        sel = self.warn_src.get_selected()
        tw = {'enabled': self.warn.get_active(), 'threshold': self.warn_thr.get_value()}
        if 0 <= sel < len(self._temp_sources):
            tw['source'] = self._temp_sources[sel]['id']
        debounce(self, 'warn', 400, lambda: self.win.set_config(temp_warning=tw))

    def load(self, st):
        c = st['config']
        self.standby.set_active(c['standby_on'])
        self.wallpaper.set_selected(c['standby_wallpaper'] - 1)
        self.wallpaper.set_sensitive(c['standby_on'])
        tw = c['temp_warning']
        self.warn.set_active(tw['enabled'])
        self.warn_thr.set_value(tw['threshold'])
        ids = [s['id'] for s in self._temp_sources]
        if tw['source'] in ids:
            self.warn_src.set_selected(ids.index(tw['source']))
        self.dev.set_subtitle('Connected' if st['connected'] else f'Not connected: {st["error"]}')
        self.fw.set_subtitle(st.get('firmware') or '—')


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title='Z890 LCD Unleashed', default_width=1000, default_height=760)
        self.state = {}
        self.loading = False
        self.client = None

        self.toasts = Adw.ToastOverlay()
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.stack = Adw.ViewStack()
        switcher = Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)
        menu = Gio.Menu()
        menu.append('About Z890 LCD Unleashed', 'app.about')
        header.pack_end(Gtk.MenuButton(icon_name='open-menu-symbolic', menu_model=menu))
        view.add_top_bar(header)
        self.banner = Adw.Banner(button_label='Retry')
        self.banner.connect('button-clicked', lambda *a: self.connect_service())
        view.add_top_bar(self.banner)

        self.display = DisplayPage(self)
        self.images = ImagesPage(self)
        self.stats = StatsPage(self)
        self.settings = SettingsPage(self)
        self.stack.add_titled_with_icon(self.display, 'display', 'Display', 'video-display-symbolic')
        self.stack.add_titled_with_icon(self.images, 'images', 'My Images', 'image-x-generic-symbolic')
        self.stack.add_titled_with_icon(self.stats, 'stats', 'Hardware Monitor', 'utilities-system-monitor-symbolic')
        self.stack.add_titled_with_icon(self.settings, 'settings', 'Settings', 'emblem-system-symbolic')
        view.set_content(self.stack)
        bar = Adw.ViewSwitcherBar(stack=self.stack)
        view.add_bottom_bar(bar)
        bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse('max-width: 700sp'))
        bp.add_setter(switcher, 'visible', False)
        bp.add_setter(bar, 'reveal', True)
        self.add_breakpoint(bp)
        self.toasts.set_child(view)
        self.set_content(self.toasts)
        for i, name in enumerate(('display', 'images', 'stats', 'settings'), 1):
            act = Gio.SimpleAction.new(f'page{i}', None)
            act.connect('activate', lambda *a, n=name: self.stack.set_visible_child_name(n))
            self.add_action(act)
            app.set_accels_for_action(f'win.page{i}', [f'<Alt>{i}'])
        page = os.environ.get('Z890LCD_PAGE')
        if page:
            self.stack.set_visible_child_name(page)
        GLib.idle_add(self.connect_service)

    # ---------------------------------------------------------------- service
    def connect_service(self):
        try:
            self.client = Client()
            self.client.on_signal(self._on_signal)
            sources = self.client.sources()
            self.stats.load_sources(sources)
            self.settings.load_sources(sources)
            self.apply_state(self.client.state())
        except (ServiceError, GLib.Error) as e:
            self.banner.set_title(f'Background service unavailable: {e}')
            self.banner.set_revealed(True)
        return False

    def _on_signal(self, name, args):
        if name == 'StateChanged':
            self.apply_state(json.loads(args[0]))

    def apply_state(self, st):
        self.state = st
        if not st.get('connected'):
            self.banner.set_title(f'LCD not connected: {st.get("error") or "unknown error"}')
            self.banner.set_revealed(True)
        elif st.get('warning_active'):
            self.banner.set_title('Temperature warning is showing on the LCD')
            self.banner.set_revealed(True)
        else:
            self.banner.set_revealed(False)
        self.loading = True
        try:
            for page in (self.display, self.images, self.stats, self.settings):
                page.load(st)
        finally:
            self.loading = False

    def set_config(self, **changes):
        self.call('SetConfig', '(s)', (json.dumps(changes),))

    def call(self, method, sig, args, ok_msg=None):
        if not self.client:
            self.toast('Background service unavailable')
            return

        def done(res, err):
            if err:
                self.toast(err)
            elif ok_msg:
                self.toast(ok_msg)
        self.client.call_async(method, sig, args, done)

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=4))


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        about = Gio.SimpleAction.new('about', None)
        about.connect('activate', self._about)
        self.add_action(about)

    def do_activate(self):
        install_css()
        win = self.props.active_window or Window(self)
        win.present()

    def _about(self, *a):
        Adw.AboutDialog(application_name='Z890 LCD Unleashed', application_icon=APP_ID, version=__version__,
                        developer_name='ssjrocks', license_type=Gtk.License.GPL_3_0,
                        website='https://github.com/ssjrocks/z890-lcd-unleashed',
                        comments='Control the ROG MAXIMUS Z890 EXTREME motherboard LCD on Linux.\n'
                                 'Not affiliated with ASUS.').present(self.props.active_window)


def main():
    Gdk.set_allowed_backends('wayland,x11,*')
    return App().run(sys.argv)
