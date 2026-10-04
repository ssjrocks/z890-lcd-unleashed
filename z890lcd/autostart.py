"""Start the background service at login: systemd user unit on Linux, HKCU Run key on Windows."""
import os
import subprocess
import sys

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
RUN_VALUE = 'Z890 LCD Unleashed'


def _service_command():
    if getattr(sys, 'frozen', False):
        return '"' + os.path.join(os.path.dirname(sys.executable), 'z890-lcd-service.exe') + '"'
    return f'"{sys.executable}" -m z890lcd.service'


def is_enabled():
    if os.name == 'nt':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
                winreg.QueryValueEx(k, RUN_VALUE)
            return True
        except OSError:
            return False
    try:
        return subprocess.run(['systemctl', '--user', 'is-enabled', 'z890-lcd.service'],
                              capture_output=True, text=True).stdout.strip() == 'enabled'
    except OSError:
        return False


def set_enabled(on):
    """Returns an error message, or '' on success."""
    if os.name == 'nt':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                if on:
                    winreg.SetValueEx(k, RUN_VALUE, 0, winreg.REG_SZ, _service_command())
                else:
                    try:
                        winreg.DeleteValue(k, RUN_VALUE)
                    except FileNotFoundError:
                        pass
            return ''
        except OSError as e:
            return str(e)
    verb = 'enable' if on else 'disable'
    try:
        r = subprocess.run(['systemctl', '--user', verb, 'z890-lcd.service'], capture_output=True, text=True)
    except OSError as e:
        return str(e)
    return r.stderr.strip() if r.returncode else ''
