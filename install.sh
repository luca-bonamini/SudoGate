#!/usr/bin/env bash
# install.sh - user half. Copies the library, the shim, the hook and the
# setup helpers.
#
# The daemon is no longer part of this half: it runs as its own system
# account, installed by install-root.sh. Nothing installed here decides
# anything — the shim only carries a command to the gate and runs the token
# it gets back.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
lib="$HOME/.local/lib/sudogate"
bindir="$HOME/bin"
unitdir="$HOME/.config/systemd/user"
sudogate_home="${SUDOGATE_HOME:-$HOME/.config/sudogate}"

mkdir -p "$lib" "$bindir" "$sudogate_home"
chmod 700 "$sudogate_home"

rm -rf "$lib/sudogate"
cp -r "$repo/sudogate" "$lib/sudogate"
find "$lib/sudogate" -name '__pycache__' -type d -prune -exec rm -rf {} +

for exe in sudogate sudogate-hook sudogate-seed sudogate-bootstrap; do
  install -m 0755 "$repo/bin/$exe" "$bindir/$exe"
done
rm -f "$bindir/sudogate-daemon"

# Earlier versions ran the daemon as this account, which is the account the
# gate exists to constrain. Retire that unit rather than leave it running.
if [ -f "$unitdir/sudogate.service" ]; then
  systemctl --user disable --now sudogate 2>/dev/null || true
  rm -f "$unitdir/sudogate.service"
  systemctl --user daemon-reload 2>/dev/null || true
  echo "Retired the per-user daemon: it now runs as its own system account."
fi

echo "User half installed."
echo "Still missing, run with root rights:  $repo/install-root.sh"
