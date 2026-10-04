"""Command-line interface. Talks to the background service (started automatically via D-Bus)."""
import argparse
import sys

from . import __version__
from .protocol import JPEG_SLOTS, PRESETS


def main(argv=None):
    p = argparse.ArgumentParser(prog='z890-lcd', description='Control the ROG MAXIMUS Z890 EXTREME LCD.')
    p.add_argument('--version', action='version', version=__version__)
    sub = p.add_subparsers(dest='cmd')
    sub.add_parser('status', help='show connection, settings and storage')
    sub.add_parser('on', help='turn the LCD on')
    sub.add_parser('off', help='turn the LCD off')
    s = sub.add_parser('brightness', help='set brightness (10-100)')
    s.add_argument('percent', type=int)
    s = sub.add_parser('preset', help='show a built-in wallpaper: ' +
                       ', '.join(f'{n}={name}' for n, (name, _, _) in PRESETS.items()))
    s.add_argument('number', type=int, choices=list(PRESETS))
    s = sub.add_parser('image', help='show an uploaded image')
    s.add_argument('slot', type=int, help=f'1-{JPEG_SLOTS}')
    s = sub.add_parser('upload', help='upload a picture (any format) to a slot and show it')
    s.add_argument('file')
    s.add_argument('--slot', type=int, default=0, help=f'1-{JPEG_SLOTS} (default: first free)')
    s.add_argument('--fit', choices=['crop', 'fit', 'stretch'], default='crop')
    s.add_argument('--background', default='#000000', help='padding colour for --fit fit')
    s.add_argument('--name')
    s.add_argument('--no-show', action='store_true')
    s = sub.add_parser('delete', help='delete an uploaded image')
    s.add_argument('slot', type=int, help=f'1-{JPEG_SLOTS}')
    s = sub.add_parser('slideshow', help='cycle through uploaded images')
    s.add_argument('slots', type=int, nargs='*', help='slots to include (default: keep current list)')
    s.add_argument('--interval', type=float, help='seconds per picture (min 2)')
    s.add_argument('--shuffle', action=argparse.BooleanOptionalAction, default=None)
    s = sub.add_parser('hwmon', help='switch to the hardware monitor (edit rows in the GUI or with --row)')
    s.add_argument('--theme', type=int, choices=[1, 2, 3, 4])
    s.add_argument('--interval', type=float)
    s.add_argument('--row', action='append', metavar='LABEL=SOURCE',
                   help='replace rows; repeat up to 3 (5 with theme 4). See `z890-lcd sources`')
    sub.add_parser('sources', help='list sensor sources for --row')
    s = sub.add_parser('standby', help='LCD while the PC sleeps / is off')
    s.add_argument('state', choices=['on', 'off'])
    s.add_argument('--wallpaper', type=int, choices=[1, 2])
    s = sub.add_parser('import-previews', help='copy wallpaper/theme previews from an Armoury Crate install '
                                               '(searches mounted drives, or give a folder)')
    s.add_argument('folder', nargs='?')
    sub.add_parser('gui', help='open the settings window')
    sub.add_parser('service', help='run the background service in the foreground')
    a = p.parse_args(argv)

    if a.cmd in (None, 'gui'):
        from .gui import main as gui_main
        return gui_main()
    if a.cmd == 'service':
        from .service import main as service_main
        return service_main()

    if a.cmd == 'import-previews':
        from . import assets
        dirs = assets.find_asset_dirs([a.folder] if a.folder else [])
        if not dirs:
            print('Armoury Crate LCD pictures not found. Mount the Windows drive (open it in Files) or pass the '
                  'folder.', file=sys.stderr)
            return 1
        print(f'imported {assets.import_from(dirs[0])} previews from {dirs[0]}')
        return 0

    from .client import Client, ServiceError
    try:
        c = Client()
        if a.cmd == 'status':
            st = c.state()
            cfg = st['config']
            print(f'LCD        : {"connected, firmware " + st["firmware"] if st["connected"] else "NOT connected: " + st["error"]}')
            print(f'Display    : {"on" if cfg["display_on"] else "off"}, brightness {cfg["brightness"]}%')
            print(f'Showing    : {st["showing"]}{"  (TEMPERATURE WARNING)" if st["warning_active"] else ""}')
            print(f'Standby    : {"on, animation " + str(cfg["standby_wallpaper"]) if cfg["standby_on"] else "off"}')
            stg = st.get('storage') or {}
            if stg:
                print(f'Storage    : {stg["free_kb"] / 1024:.1f} MB free of {stg["total_kb"] / 1024:.1f} MB')
            for s_, info in sorted(cfg['images'].items(), key=lambda kv: int(kv[0])):
                print(f'  slot {int(s_) + 1}: {info["name"]}')
        elif a.cmd in ('on', 'off'):
            c.set_config(display_on=a.cmd == 'on')
        elif a.cmd == 'brightness':
            c.set_config(brightness=a.percent)
        elif a.cmd == 'preset':
            c.set_config(mode='preset', preset=a.number)
        elif a.cmd == 'image':
            c.set_config(mode='image', image_slot=a.slot - 1)
        elif a.cmd == 'upload':
            import os
            slot = c.upload(os.path.abspath(a.file), slot=a.slot - 1, fit=a.fit, background=a.background,
                            name=a.name or '', show=not a.no_show)
            print(f'uploaded to slot {slot + 1}')
        elif a.cmd == 'delete':
            c.delete(a.slot - 1)
        elif a.cmd == 'slideshow':
            ss = {}
            if a.slots:
                ss['slots'] = [s_ - 1 for s_ in a.slots]
            if a.interval:
                ss['interval'] = a.interval
            if a.shuffle is not None:
                ss['shuffle'] = a.shuffle
            c.set_config(mode='slideshow', slideshow=ss)
        elif a.cmd == 'hwmon':
            hw = {}
            if a.theme:
                hw['theme'] = a.theme
            if a.interval:
                hw['interval'] = a.interval
            if a.row:
                hw['rows'] = [{'label': r.partition('=')[0], 'source': r.partition('=')[2] or 'custom:text'}
                              for r in a.row]
            c.set_config(mode='hwmon', hwmon=hw)
        elif a.cmd == 'sources':
            for s_ in c.sources():
                print(f'{s_["id"]:<48} {s_["category"]:<12} {s_["name"]}')
        elif a.cmd == 'standby':
            ch = {'standby_on': a.state == 'on'}
            if a.wallpaper:
                ch['standby_wallpaper'] = a.wallpaper
            c.set_config(**ch)
    except ServiceError as e:
        print(f'error: {e}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
