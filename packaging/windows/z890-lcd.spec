# PyInstaller spec for the Windows build. Run from an MSYS2 UCRT64 shell in the repository root:
#   pyinstaller packaging/windows/z890-lcd.spec
# Produces dist/z890-lcd/ with z890-lcd-gui.exe, z890-lcd-service.exe and z890-lcd.exe (CLI).
import glob
import os
import shutil

ROOT = os.path.abspath(os.path.join(SPECPATH, '..', '..'))
HERE = SPECPATH
ICON = os.path.join(HERE, 'z890-lcd.ico')

# hidapi and libusb come from MSYS2 (pacman: mingw-w64-ucrt-x86_64-hidapi / -libusb)
msys_bin = os.path.dirname(shutil.which('python') or '')
dlls = []
for pattern in ('libhidapi*.dll', 'hidapi*.dll', 'libusb-1.0*.dll'):
    dlls += [(p, '.') for p in glob.glob(os.path.join(msys_bin, pattern))]

datas = [(os.path.join(ROOT, 'z890lcd', 'previews'), os.path.join('z890lcd', 'previews'))]
hooks = {'gi': {'module-versions': {'Gtk': '4.0', 'Gdk': '4.0'}, 'icons': ['Adwaita'],
                'themes': ['Adwaita'], 'languages': ['en_US']}}
hidden = ['gi.repository.Adw', 'gi.repository.Gtk', 'gi.repository.Gdk', 'gi.repository.Gio',
          'gi.repository.GLib', 'gi.repository.Pango', 'gi.repository.PangoCairo', 'gi.repository.Graphene',
          'gi._gi_cairo', 'cairo', 'usb.backend.libusb1', 'psutil', 'PIL.Image']


def analysis(script):
    return Analysis([os.path.join(HERE, script)], pathex=[ROOT], binaries=dlls, datas=datas,
                    hiddenimports=hidden, hooksconfig=hooks, excludes=['tkinter'])


gui = analysis('entry_z890_lcd_gui.py')
svc = analysis('entry_z890_lcd_service.py')
cli = analysis('entry_z890_lcd.py')


def exe(a, name, console):
    return EXE(PYZ(a.pure), a.scripts, [], exclude_binaries=True, name=name, icon=ICON, console=console,
               version=None, upx=False)


gui_exe = exe(gui, 'z890-lcd-gui', False)
svc_exe = exe(svc, 'z890-lcd-service', False)
cli_exe = exe(cli, 'z890-lcd', True)
COLLECT(gui_exe, gui.binaries, gui.datas, svc_exe, svc.binaries, svc.datas, cli_exe, cli.binaries, cli.datas,
        name='z890-lcd', upx=False)
