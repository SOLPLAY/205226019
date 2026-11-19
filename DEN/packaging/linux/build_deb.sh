#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VERSION="${DEN_VERSION:-0.1.0}"
ARCH="$(dpkg --print-architecture)"
OUTPUT="${1:-$ROOT/dist}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

PACKAGE="$WORK/den-monitor"
install -d "$PACKAGE/DEBIAN" "$PACKAGE/usr/lib/den" "$PACKAGE/usr/bin" \
    "$PACKAGE/usr/lib/systemd/system" "$PACKAGE/etc/den" \
    "$PACKAGE/usr/share/applications" "$PACKAGE/usr/lib/den/packaging/linux"

cat >"$PACKAGE/DEBIAN/control" <<EOF
Package: den-monitor
Version: $VERSION
Section: net
Priority: optional
Architecture: $ARCH
Depends: python3 (>= 3.11), python3-yaml, python3-qrcode, python3-tk, openssl, iproute2, adduser, sudo
Maintainer: DEN Project
Description: DEN LAN node monitor, dashboard, and desktop node enrollment
 Local coordinator for DEN devices on a trusted LAN or VPN.
EOF
install -m 0755 "$ROOT/packaging/linux/postinst" "$PACKAGE/DEBIAN/postinst"
install -m 0755 "$ROOT/packaging/linux/prerm" "$PACKAGE/DEBIAN/prerm"
tar -C "$ROOT" --exclude='__pycache__' --exclude='*.pyc' \
    -cf - node monitor dashboard protocols | tar -C "$PACKAGE/usr/lib/den" -xf -
install -m 0644 "$ROOT/packaging/linux/firstboot.py" "$PACKAGE/usr/lib/den/packaging/linux/firstboot.py"
install -m 0644 "$ROOT/packaging/linux/den-monitor.service" "$PACKAGE/usr/lib/systemd/system/"
install -m 0644 "$ROOT/packaging/linux/den-dashboard.service" "$PACKAGE/usr/lib/systemd/system/"

cat >"$PACKAGE/usr/bin/den-join" <<'EOF'
#!/bin/sh
cd /usr/lib/den
exec /usr/bin/python3 -m node.setup_gui "$@"
EOF
cat >"$PACKAGE/usr/bin/den-dashboard-open" <<'EOF'
#!/bin/sh
exec xdg-open http://127.0.0.1:8765
EOF
cat >"$PACKAGE/usr/bin/den-pairing-code" <<'EOF'
#!/bin/sh
exec sudo /usr/bin/cat /var/lib/den/enrollment-code
EOF
chmod 0755 "$PACKAGE/usr/bin/den-join" "$PACKAGE/usr/bin/den-dashboard-open" "$PACKAGE/usr/bin/den-pairing-code"

cat >"$PACKAGE/usr/share/applications/den-join.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Join DEN
Comment=Enroll this computer as a DEN node
Exec=/usr/bin/den-join
Terminal=false
Categories=Network;Utility;
EOF
cat >"$PACKAGE/usr/share/applications/den-dashboard.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=DEN Monitor
Comment=Open the local DEN node monitoring dashboard
Exec=/usr/bin/den-dashboard-open
Terminal=false
Categories=Network;Utility;
EOF

install -d "$OUTPUT"
dpkg-deb --root-owner-group --build "$PACKAGE" "$OUTPUT/den-monitor_${VERSION}_${ARCH}.deb"
printf 'Built package: %s\n' "$OUTPUT/den-monitor_${VERSION}_${ARCH}.deb"
