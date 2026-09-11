#!/usr/bin/env bash
# install.sh — copia il codice nelle posizioni di esecuzione. Idempotente.
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

for exe in claude-telegram claude-tg-hook ctg-bootstrap; do
  install -m 0755 "$repo/bin/$exe" "$bindir/$exe"
done

install -m 0644 "$repo/systemd/claude-telegram.service" "$unitdir/claude-telegram.service"
systemctl --user daemon-reload

echo "Installato."
echo "  libreria: $lib/ctg"
echo "  eseguibili: $bindir/{claude-telegram,claude-tg-hook,ctg-bootstrap}"
echo "  unit: $unitdir/claude-telegram.service"
echo
echo "Passi successivi:"
echo "  1. $bindir/ctg-bootstrap        # token e chat_id"
echo "  2. systemctl --user enable --now claude-telegram"
echo "  3. registrare gli hook in ~/.claude/settings.json"
