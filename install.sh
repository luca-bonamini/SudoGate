#!/usr/bin/env bash
# install.sh - user half. Copies the library, shim, daemon, hook and unit.
# The root half (wrapper, /etc/sudogate, sudoers rule) lives in install-root.sh.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
lib="$HOME/.local/lib/sudogate"
bindir="$HOME/bin"
unitdir="$HOME/.config/systemd/user"
sudogate_home="${SUDOGATE_HOME:-$HOME/.config/sudogate}"

mkdir -p "$lib" "$bindir" "$unitdir" "$sudogate_home"
chmod 700 "$sudogate_home"

rm -rf "$lib/sudogate"
cp -r "$repo/sudogate" "$lib/sudogate"
find "$lib/sudogate" -name '__pycache__' -type d -prune -exec rm -rf {} +

for exe in sudogate sudogate-daemon sudogate-hook sudogate-seed sudogate-bootstrap; do
  install -m 0755 "$repo/bin/$exe" "$bindir/$exe"
done

install -m 0644 "$repo/systemd/sudogate.service" "$unitdir/sudogate.service"
systemctl --user daemon-reload

echo "User half installed."
echo "Still missing, run with root rights:  $repo/install-root.sh"
