#!/bin/sh
# Build dist/z890-lcd-unleashed_<version>_all.deb (needs only dpkg-deb).
set -eu
cd "$(dirname "$0")/.."
VERSION=$(python3 -c 'import z890lcd; print(z890lcd.__version__)')
APPID=io.github.ssjrocks.Z890LcdUnleashed
ROOT=$(mktemp -d)
trap 'rm -rf "$ROOT"' EXIT

PY=$ROOT/usr/lib/python3/dist-packages
mkdir -p "$PY" "$ROOT/usr/bin" "$ROOT/usr/lib/systemd/user" "$ROOT/usr/share/dbus-1/services" \
  "$ROOT/usr/lib/udev/rules.d" "$ROOT/usr/share/applications" "$ROOT/usr/share/icons/hicolor/scalable/apps" \
  "$ROOT/usr/share/metainfo" "$ROOT/usr/share/doc/z890-lcd-unleashed" "$ROOT/DEBIAN"
cp -r z890lcd "$PY/"
find "$PY" -name __pycache__ -prune -exec rm -rf {} +
for pair in "z890-lcd:z890lcd.cli" "z890-lcd-gui:z890lcd.gui" "z890-lcd-service:z890lcd.service"; do
  printf '#!/usr/bin/python3\nimport sys\nfrom %s import main\nsys.exit(main())\n' "${pair#*:}" > "$ROOT/usr/bin/${pair%%:*}"
  chmod 755 "$ROOT/usr/bin/${pair%%:*}"
done
sed 's|@BINDIR@|/usr/bin|' data/z890-lcd.service > "$ROOT/usr/lib/systemd/user/z890-lcd.service"
sed 's|@BINDIR@|/usr/bin|' data/io.github.ssjrocks.Z890Lcd.service > "$ROOT/usr/share/dbus-1/services/io.github.ssjrocks.Z890Lcd.service"
install -m 644 data/70-z890-lcd.rules "$ROOT/usr/lib/udev/rules.d/"
install -m 644 data/$APPID.desktop "$ROOT/usr/share/applications/"
install -m 644 data/icons/$APPID.svg "$ROOT/usr/share/icons/hicolor/scalable/apps/"
install -m 644 data/$APPID.metainfo.xml "$ROOT/usr/share/metainfo/"
install -m 644 README.md "$ROOT/usr/share/doc/z890-lcd-unleashed/"
cp LICENSE "$ROOT/usr/share/doc/z890-lcd-unleashed/copyright"

cat > "$ROOT/DEBIAN/control" <<CTRL
Package: z890-lcd-unleashed
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), python3-gi, python3-gi-cairo, gir1.2-gtk-4.0, gir1.2-adw-1 (>= 1.6), python3-usb, python3-pil
Maintainer: ssjrocks <70337439+ssjrocks@users.noreply.github.com>
Homepage: https://github.com/ssjrocks/z890-lcd-unleashed
Installed-Size: $(du -sk "$ROOT/usr" | cut -f1)
Description: Control the ROG MAXIMUS Z890 EXTREME motherboard LCD
 Linux replacement for the Armoury Crate LCD page: built-in wallpapers,
 your own pictures, slideshows, a configurable hardware monitor fed by
 Linux sensors, brightness, sleep-mode display and a temperature warning.
 Not affiliated with ASUS.
CTRL
cat > "$ROOT/DEBIAN/postinst" <<'POST'
#!/bin/sh
set -e
if [ "$1" = configure ]; then
  udevadm control --reload 2>/dev/null || true
  udevadm trigger --subsystem-match=hidraw --subsystem-match=usb --attr-match=idVendor=0b05 2>/dev/null || true
  systemctl --global enable z890-lcd.service 2>/dev/null || true
fi
POST
cat > "$ROOT/DEBIAN/prerm" <<'PRERM'
#!/bin/sh
set -e
if [ "$1" = remove ]; then
  systemctl --global disable z890-lcd.service 2>/dev/null || true
fi
PRERM
chmod 755 "$ROOT/DEBIAN/postinst" "$ROOT/DEBIAN/prerm"
mkdir -p dist
dpkg-deb --root-owner-group --build "$ROOT" "dist/z890-lcd-unleashed_${VERSION}_all.deb"
