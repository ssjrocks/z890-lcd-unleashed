"""System sensor discovery and formatting for the hardware-monitor display.

Everything is read from the kernel (/sys, /proc) except NVIDIA GPUs (nvidia-smi).
"""
import glob
import os
import shutil
import subprocess
import time

from .protocol import UNIT_GLYPHS

WINDOWS = os.name == 'nt'
NO_WINDOW = 0x08000000 if WINDOWS else 0  # don't flash a console window for helper processes

DEFAULT_DECIMALS = {'°C': 1, 'V': 3, 'RPM': 0, 'GHz': 2, 'MHz': 0, '%': 0, 'W': 0, 'A': 2,
                    'MB/s': 1, 'GB': 1, 'MB': 0}

CHIP_NAMES = {
    'coretemp': 'CPU', 'k10temp': 'CPU', 'zenpower': 'CPU',
    'amdgpu': 'GPU', 'nouveau': 'GPU',
    'nvme': 'NVMe', 'drivetemp': 'Drive',
    'spd5118': 'DIMM', 'jc42': 'DIMM',
    'acpitz': 'ACPI', 'iwlwifi_1': 'Wi-Fi',
}
SUPERIO_PREFIXES = ('nct', 'it87', 'it86', 'asus', 'asusec', 'asus_ec')

HWMON_KINDS = {  # attr prefix -> (category, unit, divisor)
    'temp': ('Temperature', '°C', 1000),
    'in': ('Voltage', 'V', 1000),
    'fan': ('Fan', 'RPM', 1),
    'power': ('Power', 'W', 1_000_000),
    'curr': ('Current', 'A', 1000),
    'freq': ('Frequency', 'GHz', 1_000_000_000),
}

CATEGORY_ORDER = ['Temperature', 'Load', 'Frequency', 'Fan', 'Voltage', 'Power', 'Current',
                  'Memory', 'Network', 'Disk', 'Time', 'Custom']


class Source:
    __slots__ = ('id', 'name', 'category', 'unit', 'reader')

    def __init__(self, id, name, category, unit, reader):
        self.id, self.name, self.category, self.unit, self.reader = id, name, category, unit, reader

    def as_dict(self):
        return {'id': self.id, 'name': self.name, 'category': self.category, 'unit': self.unit}


def _read_int(path):
    with open(path) as f:
        return int(f.read().strip())


def _read_str(path, default=''):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


class SensorHub:
    def __init__(self):
        self.sources = {}
        self._rates = {}
        self._gpu_cache = (0.0, [])
        self.lhm = LibreHardwareMonitor()
        self.discover()

    # ------------------------------------------------------------------ discovery
    def discover(self):
        s = {}

        def add(id, name, category, unit, reader):
            s[id] = Source(id, name, category, unit, reader)

        if WINDOWS:
            self._discover_windows(add)
        else:
            self._discover_linux(add)

        # NVIDIA GPUs
        if shutil.which('nvidia-smi'):
            for i, gpu in enumerate(self._nvidia()):
                n = f'GPU {i}' if i else 'GPU'
                add(f'nvidia:{i}:temp', f'{n} temperature ({gpu["name"]})', 'Temperature', '°C',
                    lambda i=i: self._nvidia()[i]['temp'])
                add(f'nvidia:{i}:load', f'{n} load', 'Load', '%', lambda i=i: self._nvidia()[i]['load'])
                add(f'nvidia:{i}:power', f'{n} power', 'Power', 'W', lambda i=i: self._nvidia()[i]['power'])
                add(f'nvidia:{i}:clock', f'{n} clock', 'Frequency', 'GHz',
                    lambda i=i: self._nvidia()[i]['clock'] / 1000)
                add(f'nvidia:{i}:mem', f'{n} memory used', 'Memory', 'GB',
                    lambda i=i: self._nvidia()[i]['mem'] / 1024)
                add(f'nvidia:{i}:fan', f'{n} fan', 'Fan', '%', lambda i=i: self._nvidia()[i]['fan'])

        # time
        add('time:clock', 'Clock (HH:MM)', 'Time', '', lambda: time.strftime('%H:%M'))
        add('time:clock12', 'Clock (12 h)', 'Time', '', lambda: time.strftime('%I:%M %p').lstrip('0'))
        add('time:date', 'Date', 'Time', '', lambda: time.strftime('%d %b'))
        add('time:uptime', 'Uptime', 'Time', '', self._uptime)

        # custom (value comes from the row's `param`)
        add('custom:text', 'Custom text', 'Custom', '', lambda: '')
        add('custom:command', 'Shell command output', 'Custom', '', lambda: '')
        self.sources = s
        return s

    def _discover_linux(self, add):
        # CPU basics
        add('cpu:load', 'CPU load', 'Load', '%', self._cpu_load)
        add('cpu:freq_max', 'CPU frequency (fastest core)', 'Frequency', 'GHz', lambda: self._cpu_freq(max))
        add('cpu:freq_avg', 'CPU frequency (average)', 'Frequency', 'GHz',
            lambda: self._cpu_freq(lambda v: sum(v) / len(v)))
        if self._cpu_temp_path():
            add('cpu:temp', 'CPU temperature', 'Temperature', '°C',
                lambda: _read_int(self._cpu_temp_path()) / 1000)

        # memory
        add('mem:used', 'RAM used', 'Memory', 'GB', lambda: self._mem()[0])
        add('mem:percent', 'RAM used', 'Memory', '%', lambda: self._mem()[1])
        add('mem:swap', 'Swap used', 'Memory', '%', lambda: self._mem()[2])

        # hwmon chips
        for base in sorted(glob.glob('/sys/class/hwmon/hwmon*'), key=lambda p: int(p.rsplit('hwmon', 1)[1])):
            chip = _read_str(base + '/name')
            if not chip:
                continue
            dev = os.path.basename(os.path.realpath(base + '/device')) if os.path.exists(base + '/device') else chip
            pretty = self._chip_pretty(chip, base)
            for inp in sorted(glob.glob(base + '/*_input')):
                attr = os.path.basename(inp)[:-6]
                kind = attr.rstrip('0123456789')
                if kind not in HWMON_KINDS:
                    continue
                category, unit, div = HWMON_KINDS[kind]
                if kind == 'fan' and not os.path.exists(base + f'/{attr}_label'):
                    try:  # skip empty fan headers
                        if _read_int(inp) == 0:
                            continue
                    except OSError:
                        continue
                label = _read_str(base + f'/{attr}_label') or attr
                sid = f'hwmon:{chip}@{dev}:{attr}'
                add(sid, f'{pretty}: {label}', category, unit,
                    lambda p=inp, d=div: _read_int(p) / d)

        # network
        for iface in self._net_ifaces():
            add(f'net:{iface}:rx', f'Network {iface} download', 'Network', 'MB/s',
                lambda i=iface: self._net_rate(i, 0))
            add(f'net:{iface}:tx', f'Network {iface} upload', 'Network', 'MB/s',
                lambda i=iface: self._net_rate(i, 1))

        # disks
        add('disk:root_used', 'Disk / used', 'Disk', '%', lambda: self._disk_used('/'))
        add('disk:root_free', 'Disk / free', 'Disk', 'GB', lambda: self._disk_free('/'))
        for blk in self._block_devices():
            add(f'disk:{blk}:read', f'Disk {blk} read', 'Disk', 'MB/s', lambda b=blk: self._disk_rate(b, 0))
            add(f'disk:{blk}:write', f'Disk {blk} write', 'Disk', 'MB/s', lambda b=blk: self._disk_rate(b, 1))


    def _discover_windows(self, add):
        import psutil
        psutil.cpu_percent(None)
        add('cpu:load', 'CPU load', 'Load', '%', lambda: psutil.cpu_percent(None))
        add('mem:used', 'RAM used', 'Memory', 'GB', lambda: psutil.virtual_memory().used / 1024 ** 3)
        add('mem:percent', 'RAM used', 'Memory', '%', lambda: psutil.virtual_memory().percent)
        add('mem:swap', 'Page file used', 'Memory', '%', lambda: psutil.swap_memory().percent)
        for nic in sorted(psutil.net_io_counters(pernic=True)):
            if nic.lower().startswith(('loopback', 'vethernet', 'isatap', 'teredo')):
                continue
            add(f'net:{nic}:rx', f'Network {nic} download', 'Network', 'MB/s',
                lambda n=nic: self._counter_rate(f'net:{n}:rx', psutil.net_io_counters(pernic=True)[n].bytes_recv) / 1e6)
            add(f'net:{nic}:tx', f'Network {nic} upload', 'Network', 'MB/s',
                lambda n=nic: self._counter_rate(f'net:{n}:tx', psutil.net_io_counters(pernic=True)[n].bytes_sent) / 1e6)
        drive = os.environ.get('SystemDrive', 'C:') + '\\'
        add('disk:root_used', f'Disk {drive} used', 'Disk', '%', lambda: psutil.disk_usage(drive).percent)
        add('disk:root_free', f'Disk {drive} free', 'Disk', 'GB', lambda: psutil.disk_usage(drive).free / 1e9)
        for disk in sorted((psutil.disk_io_counters(perdisk=True) or {})):
            add(f'disk:{disk}:read', f'Disk {disk} read', 'Disk', 'MB/s',
                lambda d=disk: self._counter_rate(f'disk:{d}:r', psutil.disk_io_counters(perdisk=True)[d].read_bytes) / 1e6)
            add(f'disk:{disk}:write', f'Disk {disk} write', 'Disk', 'MB/s',
                lambda d=disk: self._counter_rate(f'disk:{d}:w', psutil.disk_io_counters(perdisk=True)[d].write_bytes) / 1e6)

        # Full hardware sensors come from LibreHardwareMonitor's web server, if it is running
        cpu_temp = None
        for sid, (name, category, unit) in self.lhm.sensors().items():
            add(sid, name, category, unit, lambda i=sid: self.lhm.value(i))
            if category == 'Temperature' and cpu_temp is None and ('CPU Package' in name or 'Core (Tctl/Tdie)' in name):
                cpu_temp = sid
        if cpu_temp:
            add('cpu:temp', 'CPU temperature', 'Temperature', '°C', lambda i=cpu_temp: self.lhm.value(i))
            clocks = [i for i, (n, c, u) in self.lhm.sensors().items() if c == 'Frequency' and 'Core #' in n
                      and n.startswith(self.lhm.sensors()[cpu_temp][0].split(':')[0])]
            if clocks:
                add('cpu:freq_max', 'CPU frequency (fastest core)', 'Frequency', 'GHz',
                    lambda c=clocks: max(self.lhm.value(i) or 0 for i in c) / 1000)
        else:
            add('cpu:freq_max', 'CPU frequency', 'Frequency', 'GHz', lambda: psutil.cpu_freq().current / 1000)

    def list(self):
        order = {c: i for i, c in enumerate(CATEGORY_ORDER)}
        return sorted((x.as_dict() for x in self.sources.values()),
                      key=lambda d: (order.get(d['category'], 99), d['name']))

    # ------------------------------------------------------------------ reading
    def read(self, sid, param=''):
        if sid == 'custom:text':
            return param
        if sid == 'custom:command':
            if not param:
                return ''
            try:
                out = subprocess.run(param, shell=True, capture_output=True, text=True, timeout=3,
                                     creationflags=NO_WINDOW).stdout
                return out.strip().splitlines()[0] if out.strip() else ''
            except (subprocess.TimeoutExpired, OSError):
                return '?'
        src = self.sources.get(sid)
        if src is None:
            return None
        try:
            return src.reader()
        except (OSError, ValueError, IndexError, ZeroDivisionError, KeyError):
            return None

    def format(self, sid, value, decimals=None, unit=None, glyphs=True):
        """Format a reading for the panel. unit=None -> the source's unit; '' -> no unit."""
        src = self.sources.get(sid)
        src_unit = src.unit if src else ''
        if unit is None:
            unit = src_unit
        if value is None:
            text = '--'
        elif isinstance(value, (int, float)):
            d = DEFAULT_DECIMALS.get(src_unit, 1) if decimals is None or decimals < 0 else decimals
            text = f'{value:.{d}f}'
        else:
            text = str(value)
        return text, (UNIT_GLYPHS.get(unit, unit) if glyphs else unit)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _chip_pretty(chip, base):
        if chip.startswith(SUPERIO_PREFIXES):
            return f'Motherboard ({chip})'
        if chip == 'nvme':
            model = _read_str(base + '/device/model')
            return f'NVMe {model}' if model else 'NVMe'
        for k, v in CHIP_NAMES.items():
            if chip.startswith(k):
                return f'{v} ({chip})'
        return chip

    @staticmethod
    def _cpu_temp_path():
        for base in glob.glob('/sys/class/hwmon/hwmon*'):
            chip = _read_str(base + '/name')
            if chip in ('coretemp', 'k10temp', 'zenpower'):
                for lab in sorted(glob.glob(base + '/temp*_label')):
                    if _read_str(lab) in ('Package id 0', 'Tctl', 'Tdie'):
                        return lab.replace('_label', '_input')
                if os.path.exists(base + '/temp1_input'):
                    return base + '/temp1_input'
        return None

    def _cpu_load(self):
        with open('/proc/stat') as f:
            v = [int(x) for x in f.readline().split()[1:]]
        idle, total = v[3] + v[4], sum(v)
        prev = self._rates.get('cpu')
        self._rates['cpu'] = (idle, total)
        if not prev or total == prev[1]:
            return 0.0
        return 100.0 * (1 - (idle - prev[0]) / (total - prev[1]))

    @staticmethod
    def _cpu_freq(fn):
        vals = []
        for p in glob.glob('/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq'):
            try:
                vals.append(_read_int(p))
            except OSError:
                pass
        return fn(vals) / 1e6

    @staticmethod
    def _mem():
        m = {}
        with open('/proc/meminfo') as f:
            for line in f:
                k, v = line.split(':', 1)
                m[k] = int(v.split()[0])
        used = m['MemTotal'] - m['MemAvailable']
        swap = 100 * (m['SwapTotal'] - m['SwapFree']) / m['SwapTotal'] if m.get('SwapTotal') else 0
        return used / 1048576, 100 * used / m['MemTotal'], swap

    def _nvidia(self):
        t, data = self._gpu_cache
        if time.monotonic() - t < 1.5:
            return data
        q = 'name,temperature.gpu,utilization.gpu,power.draw,clocks.gr,memory.used,fan.speed'
        data = []
        try:
            out = subprocess.run(['nvidia-smi', f'--query-gpu={q}', '--format=csv,noheader,nounits'],
                                 capture_output=True, text=True, timeout=3, creationflags=NO_WINDOW).stdout
            for line in out.strip().splitlines():
                f = [x.strip() for x in line.split(',')]

                def num(x):
                    try:
                        return float(x)
                    except ValueError:
                        return float('nan')
                data.append({'name': f[0], 'temp': num(f[1]), 'load': num(f[2]), 'power': num(f[3]),
                             'clock': num(f[4]), 'mem': num(f[5]), 'fan': num(f[6])})
        except (OSError, subprocess.TimeoutExpired, IndexError):
            pass
        self._gpu_cache = (time.monotonic(), data)
        return data

    @staticmethod
    def _net_ifaces():
        out = []
        for p in sorted(glob.glob('/sys/class/net/*')):
            name = os.path.basename(p)
            if name == 'lo' or name.startswith(('veth', 'docker', 'br-', 'virbr', 'vnet', 'tap', 'tun')):
                continue
            out.append(name)
        return out

    def _counter_rate(self, key, value):
        now = time.monotonic()
        prev = self._rates.get(key)
        self._rates[key] = (now, value)
        if not prev or now - prev[0] <= 0:
            return 0.0
        return max(0.0, (value - prev[1]) / (now - prev[0]))

    def _net_rate(self, iface, direction):
        stat = 'rx_bytes' if direction == 0 else 'tx_bytes'
        v = _read_int(f'/sys/class/net/{iface}/statistics/{stat}')
        return self._counter_rate(f'net:{iface}:{stat}', v) / 1e6

    @staticmethod
    def _block_devices():
        return [os.path.basename(p) for p in sorted(glob.glob('/sys/block/*'))
                if not os.path.basename(p).startswith(('loop', 'ram', 'zram', 'dm-', 'sr'))]

    def _disk_rate(self, blk, direction):
        with open(f'/sys/block/{blk}/stat') as f:
            v = f.read().split()
        sectors = int(v[2] if direction == 0 else v[6])
        return self._counter_rate(f'disk:{blk}:{direction}', sectors * 512) / 1e6

    @staticmethod
    def _disk_used(path):
        st = os.statvfs(path)
        return 100 * (1 - st.f_bavail / st.f_blocks)

    @staticmethod
    def _disk_free(path):
        st = os.statvfs(path)
        return st.f_bavail * st.f_frsize / 1e9

    @staticmethod
    def _uptime():
        if WINDOWS:
            import psutil
            secs = int(time.time() - psutil.boot_time())
        else:
            with open('/proc/uptime') as f:
                secs = int(float(f.read().split()[0]))
        d, rem = divmod(secs, 86400)
        h, m = divmod(rem // 60, 60)
        return f'{d}d {h}h' if d else f'{h}h {m:02d}m'


LHM_GROUPS = {  # LibreHardwareMonitor sensor group -> our category
    'Temperatures': 'Temperature', 'Voltages': 'Voltage', 'Fans': 'Fan', 'Controls': 'Fan', 'Clocks': 'Frequency',
    'Load': 'Load', 'Powers': 'Power', 'Currents': 'Current', 'Data': 'Memory', 'SmallData': 'Memory',
    'Throughput': 'Network',
}


class LibreHardwareMonitor:
    """Reads sensors from LibreHardwareMonitor's built-in web server (Options -> Remote Web Server -> Run).

    LibreHardwareMonitor runs as administrator and loads its own driver, so this program doesn't have to.
    URL: Z890LCD_LHM_URL, default http://127.0.0.1:8085/data.json
    """

    def __init__(self, url=None):
        self.url = url or os.environ.get('Z890LCD_LHM_URL', 'http://127.0.0.1:8085/data.json')
        self._cache = (0.0, {}, {})  # time, meta, values

    def _fetch(self):
        t, meta, values = self._cache
        if time.monotonic() - t < 1.0:
            return meta, values
        meta, values = {}, {}
        if WINDOWS or os.environ.get('Z890LCD_LHM_URL'):
            try:
                import json
                import urllib.request
                with urllib.request.urlopen(self.url, timeout=1.5) as r:
                    meta, values = self.parse(json.load(r))
            except (OSError, ValueError):
                pass
        self._cache = (time.monotonic(), meta, values)
        return meta, values

    @staticmethod
    def parse(tree):
        """data.json -> ({id: (name, category, unit)}, {id: value})"""
        meta, values = {}, {}

        def walk(node, hardware, group, path):
            children = node.get('Children') or []
            text = node.get('Text', '')
            if not children and group in LHM_GROUPS and node.get('Value'):
                num, unit = _split_value(node['Value'])
                if num is None:
                    return
                sid = 'lhm:' + (node.get('SensorId') or '/'.join(path + [text]))
                meta[sid] = (f'{hardware}: {text}', LHM_GROUPS[group], unit)
                values[sid] = num
                return
            for c in children:
                is_group = c.get('Text') in LHM_GROUPS and c.get('Children')
                walk(c, hardware if is_group or not c.get('Children') else (c.get('Text') or hardware),
                     c.get('Text') if is_group else group, path + [text])

        walk(tree, '', '', [])
        return meta, values

    def sensors(self):
        return self._fetch()[0]

    def value(self, sid):
        return self._fetch()[1].get(sid)


def _split_value(text):
    """'45.0 °C' -> (45.0, '°C'); '1,250 RPM' -> (1250.0, 'RPM')."""
    text = text.strip().replace('\u00a0', ' ')
    num, _, unit = text.partition(' ')
    try:
        return float(num.replace(',', '')), unit.strip()
    except ValueError:
        return None, ''
