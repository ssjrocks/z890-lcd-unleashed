"""Hardware-monitor editor: theme, rows (label + sensor + formatting) and a live layout preview."""
import copy
import json
import math
import time

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, GLib, Gtk, Pango, PangoCairo  # noqa: E402

from ..config import MAX_ROWS  # noqa: E402
from .common import debounce, source_label, string_dropdown  # noqa: E402

THEMES = ['1 · ROG logo', '2 · Light streaks', '3 · Starfield', '4 · Gauge (up to 5 values)']
DECIMALS = [('Auto', -1), ('0', 0), ('1', 1), ('2', 2), ('3', 3)]
UNITS = [('Auto', None), ('None', ''), ('°C', '°C'), ('V', 'V'), ('RPM', 'RPM'), ('GHz', 'GHz'), ('MHz', 'MHz'),
         ('%', '%'), ('W', 'W'), ('MB/s', 'MB/s'), ('GB', 'GB')]
GLYPH_BACK = {'℃': '°C', '↊': 'V', '↌': 'RPM', '㎓': 'GHz'}


def position_name(theme, rows, i):
    if theme == 4:
        return ['Centre gauge (main)', 'Top left', 'Bottom right', 'Bottom left', 'Top right'][i]
    if rows == 1:
        return 'Centre (main)'
    if rows == 2:
        return ['Top (main)', 'Bottom'][i]
    return ['Middle (main)', 'Top', 'Bottom'][i]


class LayoutPreview(Gtk.DrawingArea):
    """Rough mock-up of where the panel puts each value. Fonts/backgrounds are the panel's own."""
    PINK = (1.0, 0.0, 0.31)

    def __init__(self):
        super().__init__(content_width=243, content_height=432)
        self.theme, self.rows = 1, []
        self.set_draw_func(self._draw)

    def update(self, theme, rows):
        self.theme, self.rows = theme, rows
        self.queue_draw()

    def _text(self, cr, x, y, text, size, rgb, align='left', bold=True):
        layout = PangoCairo.create_layout(cr)
        layout.set_font_description(Pango.FontDescription(f'Sans {"Bold" if bold else ""} {size}'))
        layout.set_text(text, -1)
        w, h = layout.get_pixel_size()
        dx = {'left': 0, 'center': -w / 2, 'right': -w}[align]
        cr.set_source_rgb(*rgb)
        cr.move_to(x + dx, y - h / 2)
        PangoCairo.show_layout(cr, layout)

    def _draw(self, area, cr, width, height):
        w, h = 243, 432
        cr.translate((width - w) / 2, (height - h) / 2)
        cr.rectangle(0, 0, w, h)
        cr.set_source_rgb(0.03, 0.03, 0.08)
        cr.fill()
        rows = [(r['label'], r['text'] + r['unit']) for r in self.rows]
        if not rows:
            return
        if self.theme == 4:
            cr.set_source_rgba(1, 1, 1, 0.25)
            cr.set_line_width(3)
            cr.arc(w / 2, h / 2, 78, 0, 2 * math.pi)
            cr.stroke()
            cr.set_source_rgba(*self.PINK, 0.8)
            cr.arc(w / 2, h / 2, 86, math.pi * 0.75, math.pi * 1.1)
            cr.stroke()
            label, val = rows[0]
            self._text(cr, w / 2, h / 2 - 26, label, 11, (1, 1, 1), 'center')
            self._text(cr, w / 2, h / 2 + 8, val, 20, (1, 1, 1), 'center')
            spots = {1: (14, 60, 'left'), 4: (w - 14, 60, 'right'), 3: (14, h - 70, 'left'),
                     2: (w - 14, h - 70, 'right')}
            for i, (label, val) in enumerate(rows[1:], 1):
                x, y, al = spots[i]
                self._text(cr, x, y, val, 14, (1, 1, 1), al)
                self._text(cr, x, y + 24, label, 9, self.PINK, al)
            return
        self._text(cr, 12, 18, 'REPUBLIC OF GAMERS', 7, (1, 1, 1), bold=False)
        order = {1: [0], 2: [0, 1], 3: [1, 0, 2]}[len(rows)]
        ys = {1: [h / 2], 2: [h * 0.33, h * 0.62], 3: [h * 0.24, h * 0.48, h * 0.72]}[len(rows)]
        for slot, y in zip(order, ys):
            label, val = rows[slot]
            self._text(cr, 16, y - 22, label, 11, self.PINK)
            self._text(cr, 30, y + 10, val, 22 if slot == 0 else 17, (1, 1, 1))


class StatsPage(Adw.Bin):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.hw = None
        self.sources = []
        self._row_widgets = []
        self._loading = False
        self._last_edit = 0.0

        outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24, margin_top=18, margin_bottom=18,
                        margin_start=18, margin_end=18)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, valign=Gtk.Align.START)
        frame = Gtk.Box(css_classes=['lcd-frame'])
        self.preview = LayoutPreview()
        frame.append(self.preview)
        left.append(frame)
        left.append(Gtk.Label(label='Live values · approximate layout', css_classes=['dim-label', 'caption']))
        self.show_btn = Gtk.Button(label='Show on LCD', css_classes=['suggested-action', 'pill'],
                                   halign=Gtk.Align.CENTER, margin_top=6)
        self.show_btn.connect('clicked', lambda *a: self.window.set_config(mode='hwmon'))
        left.append(self.show_btn)
        self.active_label = Gtk.Label(css_classes=['dim-label', 'caption'])
        left.append(self.active_label)
        outer.append(left)

        self.prefs = Adw.PreferencesPage(hexpand=True)
        g = Adw.PreferencesGroup(title='Layout')
        self.theme = Adw.ComboRow(title='Theme', model=Gtk.StringList.new(THEMES),
                                  subtitle='Background art and fonts are built into the panel')
        self.theme.connect('notify::selected', self._on_theme)
        g.add(self.theme)
        self.interval = Adw.SpinRow.new_with_range(1, 60, 1)
        self.interval.set_title('Update every (seconds)')
        self.interval.connect('notify::value', lambda *a: self._edited())
        g.add(self.interval)
        self.prefs.add(g)

        self.rows_group = Adw.PreferencesGroup(title='Values',
                                               description='The first value is the large main reading.')
        self.add_btn = Gtk.Button(icon_name='list-add-symbolic', tooltip_text='Add value',
                                  css_classes=['flat'], valign=Gtk.Align.CENTER)
        self.add_btn.connect('clicked', self._on_add)
        self.rows_group.set_header_suffix(self.add_btn)
        self.prefs.add(self.rows_group)
        outer.append(self.prefs)

        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.set_child(outer)
        self.set_child(scroller)
        GLib.timeout_add(2000, self._refresh_preview)

    # ---------------------------------------------------------------- data in
    def load_sources(self, sources):
        self.sources = sources
        self._labels = [source_label(s) for s in sources]
        self._index = {s['id']: i for i, s in enumerate(sources)}

    def load(self, state):
        cfg = state['config']
        self.active_label.set_label('Currently on the LCD' if state.get('showing') == 'hwmon' else '')
        if self.hw == cfg['hwmon'] or self._loading or time.monotonic() - self._last_edit < 3:
            return  # don't rebuild under the user's fingers while their own edit is being saved
        self._loading = True
        self.hw = copy.deepcopy(cfg['hwmon'])
        self.theme.set_selected(self.hw['theme'] - 1)
        self.interval.set_value(self.hw['interval'])
        self._rebuild_rows()
        self._loading = False
        self._refresh_preview()

    def _rebuild_rows(self):
        loading, self._loading = self._loading, True  # building widgets must not count as edits
        try:
            for w in self._row_widgets:
                self.rows_group.remove(w['expander'])
            self._row_widgets = []
            for i, row in enumerate(list(self.hw['rows'])):
                self._row_widgets.append(self._make_row(i, row))
            self.add_btn.set_sensitive(len(self.hw['rows']) < MAX_ROWS[self.hw['theme']])
        finally:
            self._loading = loading

    def _make_row(self, i, row):
        exp = Adw.ExpanderRow()
        w = {'expander': exp}
        label = Adw.EntryRow(title='Label (max 17 characters)', text=row['label'])
        label.connect('changed', lambda *a: self._edited())
        w['label'] = label
        exp.add_row(label)

        src_row = Adw.ActionRow(title='Sensor')
        dd = string_dropdown(self._labels, search=True)
        dd.set_hexpand(True)
        dd.set_size_request(260, -1)
        if row['source'] in self._index:
            dd.set_selected(self._index[row['source']])
        dd.connect('notify::selected', lambda *a: self._edited())
        src_row.add_suffix(dd)
        w['source'] = dd
        exp.add_row(src_row)

        param = Adw.EntryRow(title='Text / command', text=row.get('param', ''))
        param.connect('changed', lambda *a: self._edited())
        w['param'] = param
        exp.add_row(param)

        dec = Adw.ComboRow(title='Decimals', model=Gtk.StringList.new([d[0] for d in DECIMALS]))
        dec.set_selected(next((k for k, d in enumerate(DECIMALS) if d[1] == row.get('decimals', -1)), 0))
        dec.connect('notify::selected', lambda *a: self._edited())
        w['decimals'] = dec
        exp.add_row(dec)

        unit = Adw.ComboRow(title='Unit', model=Gtk.StringList.new([u[0] for u in UNITS]),
                            subtitle='°C, V, RPM and GHz use the panel\'s special unit symbols')
        unit.set_selected(next((k for k, u in enumerate(UNITS) if u[1] == row.get('unit')), 0))
        unit.connect('notify::selected', lambda *a: self._edited())
        w['unit'] = unit
        exp.add_row(unit)

        up = Gtk.Button(icon_name='go-up-symbolic', tooltip_text='Move up', css_classes=['flat'],
                        valign=Gtk.Align.CENTER, sensitive=i > 0)
        up.connect('clicked', lambda *a, i=i: self._move(i, -1))
        rm = Gtk.Button(icon_name='user-trash-symbolic', tooltip_text='Remove', css_classes=['flat'],
                        valign=Gtk.Align.CENTER, sensitive=len(self.hw['rows']) > 1)
        rm.connect('clicked', lambda *a, i=i: self._remove(i))
        exp.add_suffix(up)
        exp.add_suffix(rm)
        self.rows_group.add(exp)
        self._update_row_title(i, w, row)
        return w

    def _update_row_title(self, i, w, row):
        src = self.sources[self._index[row['source']]]['name'] if row['source'] in self._index else row['source']
        w['expander'].set_title(f'{row["label"] or "(no label)"}  —  {src}')
        w['expander'].set_subtitle(position_name(self.hw['theme'], len(self.hw['rows']), i))
        w['param'].set_visible(row['source'] in ('custom:text', 'custom:command'))

    # ---------------------------------------------------------------- edits out
    def _collect(self):
        rows = []
        for w in self._row_widgets:
            sel = w['source'].get_selected()
            rows.append({
                'label': w['label'].get_text()[:17],
                'source': self.sources[sel]['id'] if 0 <= sel < len(self.sources) else 'custom:text',
                'param': w['param'].get_text(),
                'decimals': DECIMALS[w['decimals'].get_selected()][1],
                'unit': UNITS[w['unit'].get_selected()][1],
            })
        self.hw['rows'] = rows
        self.hw['interval'] = self.interval.get_value()
        self.hw['theme'] = self.theme.get_selected() + 1

    def _edited(self):
        if self._loading or self.hw is None:
            return
        self._last_edit = time.monotonic()
        self._collect()
        for i, (w, row) in enumerate(zip(self._row_widgets, self.hw['rows'])):
            self._update_row_title(i, w, row)
        debounce(self, 'save', 500, lambda: self.window.set_config(hwmon=copy.deepcopy(self.hw)))
        debounce(self, 'preview', 200, self._refresh_preview)

    def _on_theme(self, *a):
        if self._loading or self.hw is None:
            return
        self._collect()
        self.hw['rows'] = self.hw['rows'][:MAX_ROWS[self.hw['theme']]]
        self._rebuild_rows()
        self._edited()

    def _on_add(self, *a):
        self._collect()
        self.hw['rows'].append({'label': 'Clock', 'source': 'time:clock', 'param': '', 'decimals': -1,
                                'unit': None})
        self._rebuild_rows()
        self._row_widgets[-1]['expander'].set_expanded(True)
        self._edited()

    def _remove(self, i):
        self._collect()
        del self.hw['rows'][i]
        self._rebuild_rows()
        self._edited()

    def _move(self, i, d):
        self._collect()
        r = self.hw['rows']
        r[i], r[i + d] = r[i + d], r[i]
        self._rebuild_rows()
        self._edited()

    def _refresh_preview(self):
        if self.hw is None or not self.get_mapped():
            return True

        def done(res, err):
            if res:
                vals = json.loads(res[0])
                for v in vals:
                    v['unit'] = GLYPH_BACK.get(v['unit'], v['unit'])
                self.preview.update(self.hw['theme'], vals)
        self.window.client.call_async('PreviewRows', '(s)', (json.dumps(self.hw['rows']),), done, 10_000)
        return True
