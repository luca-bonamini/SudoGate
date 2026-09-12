#!/usr/bin/env bash
# install-gate-root.sh — parte root. Eseguire con sudo.
# Installa il wrapper, /etc/claude-gate (patterns 0444, seed 0400), il log,
# e la riga sudoers validata con visudo.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Eseguire con sudo." >&2
  exit 1
fi

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
seed_tmp="/tmp/claude-gate-seed"

# 1. wrapper root
install -m 0755 -o root -g root "$repo/bin/claude-sudo-run" /usr/local/sbin/claude-sudo-run

# 2. /etc/claude-gate
install -d -m 0755 -o root -g root /etc/claude-gate
install -m 0444 -o root -g root "$repo/config/destructive.patterns" /etc/claude-gate/destructive.patterns

# 3. seed
if [ ! -f "$seed_tmp" ]; then
  echo "Manca $seed_tmp. Esegui prima:  ./ctg-gate-seed  (o ~/bin/ctg-gate-seed)" >&2
  exit 1
fi
install -m 0400 -o root -g root "$seed_tmp" /etc/claude-gate/seed

# 4. log audit
install -d -m 0755 -o root -g root /var/log/claude-gate

# 5. sudoers, validato prima di installare
tmp_sudoers="$(mktemp)"
cp "$repo/config/claude-gate.sudoers" "$tmp_sudoers"
if ! visudo -c -f "$tmp_sudoers"; then
  echo "sudoers non valido, non installato." >&2
  rm -f "$tmp_sudoers"
  exit 1
fi
install -m 0440 -o root -g root "$tmp_sudoers" /etc/sudoers.d/claude-gate
rm -f "$tmp_sudoers"

echo "Parte root installata."
echo "Ora, come luca:  shred -u $seed_tmp   (cancella il seed temporaneo)"
echo "E abilita il daemon:  systemctl --user enable --now ctg-gate"
