#!/usr/bin/env bash
# install-gate.sh — parte utente (luca). Copia lib, shim, daemon, hook e unit.
# La parte root (wrapper, /etc/claude-gate, sudoers) sta in install-gate-root.sh.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
lib="$HOME/.local/lib/claude-telegram"
bindir="$HOME/bin"
unitdir="$HOME/.config/systemd/user"
ctg_home="${CTG_HOME:-$HOME/.claude/telegram}"

mkdir -p "$lib" "$bindir" "$unitdir" "$ctg_home"
chmod 700 "$ctg_home"

rm -rf "$lib/ctg"
cp -r "$repo/ctg" "$lib/ctg"
find "$lib/ctg" -name '__pycache__' -type d -prune -exec rm -rf {} +

for exe in claude-sudo ctg-gate claude-tg-gate ctg-gate-seed ctg-bootstrap; do
  install -m 0755 "$repo/bin/$exe" "$bindir/$exe"
done

install -m 0644 "$repo/systemd/ctg-gate.service" "$unitdir/ctg-gate.service"
systemctl --user daemon-reload

echo "Parte utente installata."
echo "Manca la parte root:  sudo $repo/install-gate-root.sh"
