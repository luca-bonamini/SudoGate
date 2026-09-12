#!/usr/bin/env bash
# install-gate-root.sh — parte root. Eseguire con sudo.
# Installa il wrapper, /etc/sudogate (patterns 0444, seed 0400), il log,
# e la riga sudoers validata con visudo.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Eseguire con sudo." >&2
  exit 1
fi

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# L'utente per cui installare: chi ha invocato sudo, non root.
target_user="${SUDO_USER:-$USER}"
if [ "$target_user" = "root" ]; then
  echo "Esegui con sudo da un utente normale, non come root diretto." >&2
  exit 1
fi
echo "Installo sudogate per l'utente: $target_user"
seed_tmp="${SUDOGATE_SEED_TMP:-/tmp/sudogate-seed}"

# 1. wrapper root
install -m 0755 -o root -g root "$repo/bin/sudogate-run" /usr/local/sbin/sudogate-run

# 2. /etc/sudogate
install -d -m 0755 -o root -g root /etc/sudogate
install -m 0444 -o root -g root "$repo/config/destructive.patterns" /etc/sudogate/destructive.patterns

# 3. seed
if [ ! -f "$seed_tmp" ]; then
  echo "Manca $seed_tmp. Esegui prima:  ~/bin/sudogate-seed" >&2
  exit 1
fi
install -m 0400 -o root -g root "$seed_tmp" /etc/sudogate/seed

# 4. log audit
install -d -m 0755 -o root -g root /var/log/sudogate

# 5. sudoers, validato prima di installare
tmp_sudoers="$(mktemp)"
sed "s/__USER__/$target_user/g" "$repo/config/sudogate.sudoers.template" > "$tmp_sudoers"
if ! visudo -c -f "$tmp_sudoers"; then
  echo "sudoers non valido, non installato." >&2
  rm -f "$tmp_sudoers"
  exit 1
fi
install -m 0440 -o root -g root "$tmp_sudoers" /etc/sudoers.d/sudogate
rm -f "$tmp_sudoers"

echo "Parte root installata."
echo "Ora, come $target_user:  shred -u $seed_tmp   (cancella il seed temporaneo)"
echo "E abilita il daemon:  systemctl --user enable --now sudogate"
