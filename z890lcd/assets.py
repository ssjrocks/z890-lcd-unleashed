"""Preview images of the panel's built-in wallpapers, animations and hardware-monitor themes.

Previews bundled in z890lcd/previews/ are used first. If they are missing, they can be imported from an
Armoury Crate installation the user already has (for example on a Windows partition of the same PC)
into ~/.local/share/z890-lcd/previews.
"""
import glob
import os

from PIL import Image

from .config import DATA_DIR

BUNDLED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'previews')
PREVIEW_DIR = os.path.join(DATA_DIR, 'previews')  # where imported previews go
ASSET_SUBDIR = os.path.join('resources', 'src', 'pages', 'lcd', 'common', 'images', '5')
AC_VIEW_DIR = os.path.join('Program Files (x86)', 'ASUS', 'ArmouryDevice', 'View')

# preview name -> file name inside the Armoury Crate asset folder
PRESET_FILES = {
    1: 'ex_5_launch1.gif', 2: 'ex_5_launch2.gif',
    3: 'ex_5_rog1.png', 4: 'ex_5_rog2.png', 5: 'ex_5_rog3.png',
    6: 'ex_5_rog4.png', 7: 'ex_5_rog5.png', 8: 'ex_5_rog6.png',
}
THEME_FILES = {1: 'hw_st_01.gif', 2: 'hw_st_02.gif', 3: 'hw_st_03.gif', 4: 'hw_st_04.gif'}
THUMB_SIZE = (270, 480)


def preset_preview(n):
    return _existing(f'preset{n}')


def theme_preview(n):
    return _existing(f'theme{n}')


def have_previews():
    return all(preset_preview(n) for n in PRESET_FILES)


def _existing(stem):
    for folder in (BUNDLED_DIR, PREVIEW_DIR):
        for ext in ('.gif', '.jpg'):
            p = os.path.join(folder, stem + ext)
            if os.path.exists(p):
                return p
    return None


def _mount_points():
    """Mounted filesystems that could hold a Windows installation."""
    points = []
    try:
        with open('/proc/self/mounts') as f:
            for line in f:
                dev, mnt, fstype = line.split()[:3]
                if fstype in ('ntfs', 'ntfs3', 'fuseblk', 'vfat', 'exfat') or mnt.startswith(('/media', '/run/media',
                                                                                                 '/mnt')):
                    points.append(mnt.replace('\\040', ' '))
    except OSError:
        pass
    return points


def find_asset_dirs(extra=()):
    """Folders containing Armoury Crate's LCD artwork, on mounted drives or below the given folders."""
    found = []
    for base in list(extra) + _mount_points():
        candidates = [os.path.join(base, AC_VIEW_DIR, '*', ASSET_SUBDIR), os.path.join(base, '*', ASSET_SUBDIR),
                      os.path.join(base, ASSET_SUBDIR), base]
        for pattern in candidates:
            for d in glob.glob(pattern):
                if d not in found and _locate(d, PRESET_FILES[1]):
                    found.append(d)
    return found


def _locate(folder, name):
    for sub in ('', 'img_or_anim/bg_anim', 'img_or_anim/bg_img', 'hw_monitor/bg_anim'):
        p = os.path.join(folder, sub, name)
        if os.path.exists(p):
            return p
    return None


def import_from(folder):
    """Copy/convert the previews. Returns the number of files imported."""
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    count = 0
    jobs = [(f'preset{n}', f) for n, f in PRESET_FILES.items()] + [(f'theme{n}', f) for n, f in THEME_FILES.items()]
    for stem, name in jobs:
        src = _locate(folder, name)
        if not src:
            continue
        img = Image.open(src)
        if getattr(img, 'is_animated', False):
            dst = os.path.join(PREVIEW_DIR, stem + '.gif')
            with open(src, 'rb') as fi, open(dst, 'wb') as fo:  # already preview-sized
                fo.write(fi.read())
        else:
            img = img.convert('RGB')
            img.thumbnail(THUMB_SIZE, Image.LANCZOS)
            img.save(os.path.join(PREVIEW_DIR, stem + '.jpg'), quality=88)
        count += 1
    return count


def load_frames(path, size=None):
    """[(PIL RGB image, duration_ms)] for a GIF or still picture."""
    img = Image.open(path)
    frames = []
    for i in range(getattr(img, 'n_frames', 1)):
        img.seek(i)
        f = img.convert('RGB')
        if size:
            f = f.resize(size, Image.LANCZOS)
        frames.append((f, max(20, img.info.get('duration', 100) or 100)))
    return frames
