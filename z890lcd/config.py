"""Persistent settings (~/.config/z890-lcd/config.json) and the local image library."""
import copy
import json
import os

from .protocol import JPEG_SLOTS, PRESETS

CONFIG_DIR = os.path.join(os.environ.get('XDG_CONFIG_HOME', os.path.expanduser('~/.config')), 'z890-lcd')
DATA_DIR = os.path.join(os.environ.get('XDG_DATA_HOME', os.path.expanduser('~/.local/share')), 'z890-lcd')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'config.json')
IMAGE_DIR = os.path.join(DATA_DIR, 'images')

MODES = ('preset', 'image', 'slideshow', 'hwmon')
MAX_ROWS = {1: 3, 2: 3, 3: 3, 4: 5}
MIN_SLIDESHOW_INTERVAL = 2.0  # the panel fades each change in over ~0.5 s and blanks if changed faster than ~3/s
MIN_HWMON_INTERVAL = 1.0

DEFAULTS = {
    'display_on': True,
    'brightness': 80,
    'standby_on': True,
    'standby_wallpaper': 2,
    'mode': 'preset',
    'preset': 1,
    'image_slot': 0,
    'slideshow': {'slots': [], 'interval': 10.0, 'shuffle': False},
    'hwmon': {
        'theme': 1,
        'interval': 2.0,
        'rows': [
            {'label': 'CPU', 'source': 'cpu:temp', 'param': '', 'decimals': -1, 'unit': None},
            {'label': 'GPU', 'source': 'nvidia:0:temp', 'param': '', 'decimals': -1, 'unit': None},
            {'label': 'CPU Load', 'source': 'cpu:load', 'param': '', 'decimals': -1, 'unit': None},
        ],
    },
    'temp_warning': {'enabled': False, 'source': 'cpu:temp', 'threshold': 90, 'hysteresis': 5},
    'images': {},  # slot (str) -> {"name": ..., "file": ...}  - panel can't return pictures, so we keep copies
}


def _merge(base, override):
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict) and k != 'images':
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def validate(cfg):
    """Clamp everything to what the firmware accepts. Returns a new dict."""
    c = _merge(DEFAULTS, cfg)
    c['brightness'] = max(10, min(100, int(c['brightness'])))
    c['standby_wallpaper'] = 2 if c['standby_wallpaper'] == 2 else 1
    c['display_on'] = bool(c['display_on'])
    c['standby_on'] = bool(c['standby_on'])
    if c['mode'] not in MODES:
        c['mode'] = 'preset'
    c['preset'] = {9: 1, 10: 2}.get(c['preset'], c['preset'])  # old builds offered duplicates as 9/10
    if c['preset'] not in PRESETS:
        c['preset'] = 1
    c['image_slot'] = max(0, min(JPEG_SLOTS - 1, int(c['image_slot'])))
    ss = c['slideshow']
    ss['slots'] = [int(s) for s in ss.get('slots', []) if 0 <= int(s) < JPEG_SLOTS]
    ss['interval'] = max(MIN_SLIDESHOW_INTERVAL, float(ss.get('interval', 10)))
    hw = c['hwmon']
    hw['theme'] = hw['theme'] if hw.get('theme') in MAX_ROWS else 1
    hw['interval'] = max(MIN_HWMON_INTERVAL, float(hw.get('interval', 2)))
    rows = []
    for r in hw.get('rows', [])[:MAX_ROWS[hw['theme']]]:
        rows.append({
            'label': str(r.get('label', ''))[:17],
            'source': str(r.get('source', 'custom:text')),
            'param': str(r.get('param', '')),
            'decimals': int(r.get('decimals', -1)) if r.get('decimals') is not None else -1,
            'unit': r.get('unit'),
        })
    hw['rows'] = rows or copy.deepcopy(DEFAULTS['hwmon']['rows'][:1])
    tw = c['temp_warning']
    tw['threshold'] = float(tw.get('threshold', 90))
    tw['hysteresis'] = max(1.0, float(tw.get('hysteresis', 5)))
    c['images'] = {str(k): v for k, v in c.get('images', {}).items() if str(k).isdigit()}
    return c


def load():
    try:
        with open(CONFIG_FILE) as f:
            return validate(json.load(f))
    except (OSError, ValueError):
        return validate({})


def save(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = CONFIG_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CONFIG_FILE)
