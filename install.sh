#!/usr/bin/env bash
# install-gate.sh — parte utente (luca). Copia lib, shim, daemon, hook e unit.
# La parte root (wrapper, /etc/sudogate, sudoers) sta in install-gate-root.sh.
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

echo "Parte utente installata."
echo "Manca la parte root:  sudo $repo/install-gate-root.sh"
