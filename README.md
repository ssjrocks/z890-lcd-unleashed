# Z890 LCD Unleashed

Control the 5" LCD on the **ASUS ROG MAXIMUS Z890 EXTREME** motherboard from Linux – no Armoury Crate,
no Windows.

* **Built-in wallpapers** – the 2 animations and 6 pictures stored on the panel.
* **Your own pictures** – any format, cropped or fitted to the 720 × 1280 portrait screen with a live
  preview; 8 slots on the panel.
* **Slideshows** of your pictures, in order or shuffled.
* **Hardware monitor** – the panel's 4 themes with up to 5 values, each with your own label and any
  Linux sensor: CPU/GPU temperatures, loads and clocks, every motherboard fan and voltage, NVMe and DIMM
  temperatures, RAM, network and disk speeds, a clock, custom text or the output of any shell command.
* **Brightness**, display on/off, and what to show while the PC sleeps or is off.
* **Temperature warning** – switches to the panel's built-in warning screen when a sensor gets too hot.
* A background service keeps everything running with the window closed, plus a `z890-lcd` CLI.

> Not affiliated with or endorsed by ASUS. "ROG" and "Armoury Crate" are trademarks of ASUSTeK.
> Tested with panel firmware 0107.

## Install

### Ubuntu / Debian (.deb)

Download the `.deb` from the releases page, then:

```sh
sudo apt install ./z890-lcd-unleashed_0.1.0_all.deb
systemctl --user enable --now z890-lcd.service
```

### Any distro (install script)

```sh
# dependencies - Debian/Ubuntu:
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 python3-usb python3-pil
# Fedora: sudo dnf install python3-gobject gtk4 libadwaita python3-pyusb python3-pillow
# Arch:   sudo pacman -S python-gobject gtk4 libadwaita python-pyusb python-pillow

git clone https://github.com/ssjrocks/z890-lcd-unleashed
cd z890-lcd-unleashed
./install.sh          # per user, asks for sudo once for the udev rule
```

`./install.sh --uninstall` removes it again. `sudo ./install.sh --system` installs for all users.

The udev rule (`data/70-z890-lcd.rules`) gives the logged-in user access to the LCD; without it only
root can talk to the panel.

## Use

Open **Z890 LCD Unleashed** from the app menu. Pages: **Display** (on/off, brightness, built-in
wallpapers), **My Images** (upload, show, delete, slideshow), **Hardware Monitor** (theme, values,
live preview) and **Settings** (sleep display, temperature warning, autostart). Alt+1…4 switch pages.

From a terminal:

```sh
z890-lcd status
z890-lcd brightness 60
z890-lcd preset 2                        # starfield ROG animation
z890-lcd upload ~/Pictures/wallpaper.png --fit crop
z890-lcd slideshow 1 2 3 --interval 15 --shuffle
z890-lcd sources                         # list sensor ids
z890-lcd hwmon --theme 4 --row CPU=cpu:temp --row GPU=nvidia:0:temp --row Time=time:clock
```

## Limits of the panel firmware

* Uploaded **animated GIFs can't be shown** on the main screen – the firmware stores them but refuses to
  display them (Armoury Crate has the same restriction). Animated content is limited to the built-in
  animations and the hardware-monitor themes.
* Every image change fades in over about half a second, and more than ~3 changes per second blank the
  screen, so slideshows are limited to one picture every 2 seconds or more.
* Hardware-monitor fonts, colours and backgrounds are built into the panel; you choose the theme, the
  values, their labels and formatting.

## How it works

`z890lcd/protocol.py` implements the USB protocol described in [docs/PROTOCOL.md](docs/PROTOCOL.md).
`z890-lcd-service` (a systemd user service, started on demand over D-Bus) owns the device, re-applies
your settings after unplug or resume from sleep, and keeps stats and slideshows updating. The GTK 4 /
libadwaita app and the CLI talk to it over the session bus (`io.github.ssjrocks.Z890Lcd`).

## Licence

GPL-3.0-or-later.
