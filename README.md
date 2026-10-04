# Z890 LCD Unleashed

Control the 5" LCD on the **ASUS ROG MAXIMUS Z890 EXTREME** motherboard from Linux (and Windows) – no
Armoury Crate needed.

<p align="center">
  <img src="docs/images/lcd-hwmon-gauge.jpg" alt="The motherboard LCD showing live Linux sensor values in the gauge theme" height="420">
  &nbsp;
  <img src="docs/images/app-hwmon.png" alt="The Hardware Monitor page of the app" height="420">
</p>

* **Built-in wallpapers** – the 2 animations and 6 pictures stored on the panel, with real thumbnails
  and playing animation previews (imported from Armoury Crate if they aren't bundled).
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

## Screenshots

| | |
|---|---|
| ![Display page: on/off, brightness and built-in wallpapers](docs/images/app-display.png) | ![My Images page with an uploaded picture](docs/images/app-images.png) |
| **Display** – power, brightness, built-in wallpapers | **My Images** – 8 slots on the panel, slideshow |
| ![Upload dialog with a live 720 × 1280 preview](docs/images/app-upload.png) | ![Settings page](docs/images/app-settings.png) |
| **Upload** – crop, fit, zoom and rotate with a live preview | **Settings** – sleep display, temperature warning, autostart |

### On the LCD

<p align="center">
  <img src="docs/images/lcd-hwmon-theme1.jpg" alt="Theme 1 with GPU, CPU and fan values" height="250">
  <img src="docs/images/lcd-custom-image.jpg" alt="A custom picture uploaded from Linux, shown in the case" height="250">
  <img src="docs/images/lcd-wallpaper.jpg" alt="A built-in ROG wallpaper" height="250">
  <img src="docs/images/lcd-neon-animation.jpg" alt="The built-in neon ROG animation" height="250">
</p>

Phone photos of the real panel: hardware monitor theme 1, a picture uploaded from Linux, a built-in
wallpaper and the neon ROG animation. More in [docs/screenshots.md](docs/screenshots.md).

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

### Windows

Download `z890-lcd-unleashed-<version>-windows-setup.exe` from the releases page and run it. It installs
the app, a Start menu entry and (optionally) starts the background service when you sign in.

* **Hardware sensors:** install [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor),
  run it as administrator and turn on *Options → Remote Web Server → Run* (port 8085). Z890 LCD Unleashed
  then offers every temperature, fan, voltage and clock it reports. Without it you still get CPU load, RAM,
  disk, network, NVIDIA GPU, clock, text and command values.
* **Uploading your own pictures** uses the LCD's second USB interface, which needs the WinUSB driver.
  If Armoury Crate was never installed: run [Zadig](https://zadig.akeo.ie/), choose *Options → List All
  Devices*, pick **Motherboard LCD Panel (Interface 0)** – *not* Interface 1 – select **WinUSB** and press
  *Replace Driver*. Everything else (wallpapers, brightness, stats) works without it.
* **Armoury Crate:** don't let both control the LCD at the same time – uninstall Armoury Crate or disable
  its LCD feature, otherwise they overwrite each other.

The settings live in `%APPDATA%\z890-lcd`, the service log in `%LOCALAPPDATA%\z890-lcd\service.log`.

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
