#!/bin/sh
# Install Z890 LCD Unleashed without pip, using the distro's Python packages.
#   ./install.sh               install for the current user (~/.local); asks for sudo for the udev rule
#   sudo ./install.sh --system install for all users (/usr/local)
#   ./install.sh --uninstall   (or sudo ./install.sh --system --uninstall)
set -eu
cd "$(dirname "$0")"
MODE=user; ACTION=install
for arg in "$@"; do
  case "$arg" in
    --system) MODE=system ;;
    --uninstall) ACTION=uninstall ;;
    -h|--help) sed -n '2,5p' "$0"; exit 0 ;;
    *) echo "unknown option $arg" >&2; exit 1 ;;
  esac
done

if [ "$MODE" = system ]; then
  [ "$(id -u)" = 0 ] || { echo "--system needs root (sudo)" >&2; exit 1; }
  PREFIX=/usr/local; LIB=$PREFIX/lib/z890-lcd-unleashed; BIN=$PREFIX/bin; SHARE=$PREFIX/share
  UNITDIR=/etc/systemd/user; DBUSDIR=/usr/share/dbus-1/services; SUDO=""
else
  PREFIX=$HOME/.local; LIB=$PREFIX/lib/z890-lcd-unleashed; BIN=$PREFIX/bin; SHARE=$PREFIX/share
  UNITDIR=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user; DBUSDIR=$SHARE/dbus-1/services; SUDO=sudo
fi
APPID=io.github.ssjrocks.Z890LcdUnleashed
RULE=/etc/udev/rules.d/70-z890-lcd.rules

user_systemctl() {  # run systemctl --user as the invoking desktop user
  if [ "$MODE" = user ]; then systemctl --user "$@" 2>/dev/null || true; fi
}

if [ "$ACTION" = uninstall ]; then
  user_systemctl disable --now z890-lcd.service
  rm -rf "$LIB" "$BIN/z890-lcd" "$BIN/z890-lcd-gui" "$BIN/z890-lcd-service" \
    "$UNITDIR/z890-lcd.service" "$DBUSDIR/io.github.ssjrocks.Z890Lcd.service" \
    "$SHARE/applications/$APPID.desktop" "$SHARE/icons/hicolor/scalable/apps/$APPID.svg" \
    "$SHARE/metainfo/$APPID.metainfo.xml"
  $SUDO rm -f "$RULE" && $SUDO udevadm control --reload || true
  user_systemctl daemon-reload
  echo "Uninstalled. Your settings and images are kept in ~/.config/z890-lcd and ~/.local/share/z890-lcd."
  exit 0
fi

missing=""
python3 -c 'import gi; gi.require_version("Gtk","4.0"); gi.require_version("Adw","1"); from gi.repository import Gtk, Adw' 2>/dev/null || missing="$missing python3-gi gir1.2-gtk-4.0 gir1.2-adw-1"
python3 -c 'import usb.core' 2>/dev/null || missing="$missing python3-usb"
python3 -c 'import PIL' 2>/dev/null || missing="$missing python3-pil"
if [ -n "$missing" ]; then
  echo "Missing Python packages:$missing"
  echo "  Debian/Ubuntu: sudo apt install$missing"
  echo "  Fedora:        sudo dnf install python3-gobject gtk4 libadwaita python3-pyusb python3-pillow"
  echo "  Arch:          sudo pacman -S python-gobject gtk4 libadwaita python-pyusb python-pillow"
  exit 1
fi

echo "Installing to $PREFIX"
mkdir -p "$LIB" "$BIN" "$UNITDIR" "$DBUSDIR" "$SHARE/applications" "$SHARE/icons/hicolor/scalable/apps" "$SHARE/metainfo"
rm -rf "$LIB/z890lcd"
cp -r z890lcd "$LIB/"
find "$LIB" -name __pycache__ -prune -exec rm -rf {} +
for pair in "z890-lcd:z890lcd.cli" "z890-lcd-gui:z890lcd.gui" "z890-lcd-service:z890lcd.service"; do
  name=${pair%%:*}; mod=${pair#*:}
  printf '#!/usr/bin/env python3\nimport sys\nsys.path.insert(0, "%s")\nfrom %s import main\nsys.exit(main())\n' "$LIB" "$mod" > "$BIN/$name"
  chmod 755 "$BIN/$name"
done
sed "s|@BINDIR@|$BIN|" data/z890-lcd.service > "$UNITDIR/z890-lcd.service"
sed "s|@BINDIR@|$BIN|" data/io.github.ssjrocks.Z890Lcd.service > "$DBUSDIR/io.github.ssjrocks.Z890Lcd.service"
sed "s|^Exec=z890-lcd-gui|Exec=$BIN/z890-lcd-gui|" data/$APPID.desktop > "$SHARE/applications/$APPID.desktop"
cp data/icons/$APPID.svg "$SHARE/icons/hicolor/scalable/apps/"
cp data/$APPID.metainfo.xml "$SHARE/metainfo/"

if ! cmp -s data/70-z890-lcd.rules "$RULE" 2>/dev/null; then
  echo "Installing udev rule (gives your user access to the LCD)"
  $SUDO install -m 644 data/70-z890-lcd.rules "$RULE"
  $SUDO udevadm control --reload
  $SUDO udevadm trigger --subsystem-match=hidraw --subsystem-match=usb --attr-match=idVendor=0b05 || true
fi

gtk-update-icon-cache -q -t "$SHARE/icons/hicolor" 2>/dev/null || true
update-desktop-database -q "$SHARE/applications" 2>/dev/null || true
user_systemctl daemon-reload
user_systemctl enable --now z890-lcd.service
echo "Done. Open \"Z890 LCD Unleashed\" from your app menu, or run: z890-lcd status"
[ "$MODE" = system ] && echo "Each user can enable the background service with: systemctl --user enable --now z890-lcd.service"
case ":$PATH:" in *":$BIN:"*) ;; *) echo "Note: $BIN is not on your PATH." ;; esac
