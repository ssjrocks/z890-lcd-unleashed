"""Turn any picture into the 720x1280 JPEG the panel expects."""
from io import BytesIO

from PIL import Image, ImageOps

from .protocol import HEIGHT, WIDTH


def render(path, fit='crop', focus_x=0.5, focus_y=0.5, zoom=1.0, rotate=0, background='#000000'):
    """Return a 720x1280 RGB PIL image.

    fit:  'crop'    fill the screen, cutting off what doesn't fit (focus_x/y choose which part stays)
          'fit'     show the whole picture, padding with `background`
          'stretch' distort to fill
    zoom: extra magnification (>= 1) applied in crop mode.
    rotate: 0/90/180/270 degrees clockwise.
    """
    img = Image.open(path)
    img.seek(0)
    img = ImageOps.exif_transpose(img)
    if img.mode in ('RGBA', 'LA', 'P'):
        img = img.convert('RGBA')
        bg = Image.new('RGBA', img.size, background)
        img = Image.alpha_composite(bg, img)
    img = img.convert('RGB')
    if rotate:
        img = img.rotate(-int(rotate), expand=True)

    if fit == 'stretch':
        return img.resize((WIDTH, HEIGHT), Image.LANCZOS)
    if fit == 'fit':
        return ImageOps.pad(img, (WIDTH, HEIGHT), Image.LANCZOS, color=background)

    # crop: scale so the picture covers the screen, then pick a window around the focus point
    scale = max(WIDTH / img.width, HEIGHT / img.height) * max(1.0, zoom)
    w, h = round(img.width * scale), round(img.height * scale)
    img = img.resize((w, h), Image.LANCZOS)
    left = round((w - WIDTH) * min(max(focus_x, 0), 1))
    top = round((h - HEIGHT) * min(max(focus_y, 0), 1))
    return img.crop((left, top, left + WIDTH, top + HEIGHT))


def to_jpeg(img, quality=90, max_bytes=2_000_000):
    """Encode, lowering quality if the file would be unreasonably large for the panel's slow flash."""
    while True:
        buf = BytesIO()
        img.save(buf, 'JPEG', quality=quality, optimize=True)
        if buf.tell() <= max_bytes or quality <= 50:
            return buf.getvalue()
        quality -= 10


def thumbnail(img, height=320):
    t = img.copy()
    t.thumbnail((height * WIDTH // HEIGHT, height), Image.LANCZOS)
    return t
