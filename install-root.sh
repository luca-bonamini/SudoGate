#!/usr/bin/env bash
# install-root.sh — root half. Run with root rights.
# Installs the wrapper, the root-owned library it imports, /etc/sudogate
# (patterns 0444, seed 0400), the audit log directory, and the sudoers rule,
# validated with visudo first.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this with root rights." >&2
  exit 1
fi

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The account to install for: whoever invoked the escalation, not root.
target_user="${SUDO_USER:-$USER}"
if [ "$target_user" = "root" ]; then
  echo "Escalate from a normal account; do not run this as root directly." >&2
  exit 1
fi
echo "Installing sudogate for account: $target_user"
seed_tmp="${SUDOGATE_SEED_TMP:-/tmp/sudogate-seed}"

# 1. root wrapper
install -m 0755 -o root -g root "$repo/bin/sudogate-run" /usr/local/sbin/sudogate-run

# 1b. the library the wrapper imports, root-owned.
#     It used to be imported from the invoking user's ~/.local/lib/sudogate,
#     which let that user replace the code checking the TOTP.
lib=/usr/local/lib/sudogate
rm -rf "$lib/sudogate"
install -d -m 0755 -o root -g root "$lib" "$lib/sudogate"
for f in "$repo"/sudogate/*.py; do
  install -m 0444 -o root -g root "$f" "$lib/sudogate/$(basename "$f")"
done

# 2. /etc/sudogate
install -d -m 0755 -o root -g root /etc/sudogate
install -m 0444 -o root -g root "$repo/config/destructive.patterns" /etc/sudogate/destructive.patterns

# 3. TOTP seed
if [ ! -f "$seed_tmp" ]; then
  echo "Missing $seed_tmp. Run this first:  ~/bin/sudogate-seed" >&2
  exit 1
fi
install -m 0400 -o root -g root "$seed_tmp" /etc/sudogate/seed

# 4. optional policy: require a TOTP code for every command, not only
#    destructive ones. Root-owned, so the user cannot clear it.
if [ "${SUDOGATE_TOTP_ALWAYS:-0}" = "1" ]; then
  : > /etc/sudogate/totp_always
  chmod 0444 /etc/sudogate/totp_always
  chown root:root /etc/sudogate/totp_always
  echo "Policy: a TOTP code is required for EVERY command."
else
  rm -f /etc/sudogate/totp_always
  echo "Policy: a TOTP code is required for destructive commands only."
  echo "  To require it for every command, re-run with SUDOGATE_TOTP_ALWAYS=1"
fi

# 5. audit log
install -d -m 0755 -o root -g root /var/log/sudogate

# 6. sudoers rule, validated before install
tmp_sudoers="$(mktemp)"
sed "s/__USER__/$target_user/g" "$repo/config/sudogate.sudoers.template" > "$tmp_sudoers"
if ! visudo -c -f "$tmp_sudoers"; then
  echo "sudoers rule is invalid, nothing installed." >&2
  rm -f "$tmp_sudoers"
  exit 1
fi
install -m 0440 -o root -g root "$tmp_sudoers" /etc/sudoers.d/sudogate
rm -f "$tmp_sudoers"

echo "Root half installed."
echo "Now, as $target_user:  shred -u $seed_tmp   (delete the temporary seed)"
echo "Then enable the daemon:  systemctl --user enable --now sudogate"
