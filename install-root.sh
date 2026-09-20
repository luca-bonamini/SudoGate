#!/usr/bin/env bash
# install-root.sh — root half. Run with root rights.
#
# Installs everything the gate relies on into places the gated account cannot
# write: the wrapper and the library it imports, the daemon and its system
# account, /etc/sudogate (config 0400, patterns 0444, seed 0400), the audit
# log directory, and the sudoers rule, validated with visudo first.
#
# The daemon runs as its own account, not as the user being gated. That is
# what makes an approval mean something: the command shown on the phone and
# the command root runs are the same record, in a directory the gated user
# can neither read nor write.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this with root rights." >&2
  exit 1
fi

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The account to gate: whoever invoked the escalation, not root.
target_user="${SUDO_USER:-$USER}"
if [ "$target_user" = "root" ]; then
  echo "Escalate from a normal account; do not run this as root directly." >&2
  exit 1
fi
target_uid="$(id -u "$target_user")"
target_home="$(getent passwd "$target_user" | cut -d: -f6)"
echo "Gating account: $target_user (uid $target_uid)"
seed_tmp="${SUDOGATE_SEED_TMP:-/tmp/sudogate-seed}"
daemon_user="sudogate"

# 1. the daemon's own account: no login, no home, no shell
if ! id -u "$daemon_user" >/dev/null 2>&1; then
  useradd --system --no-create-home --home-dir /nonexistent \
          --shell /usr/sbin/nologin "$daemon_user"
  echo "Created system account: $daemon_user"
fi

# 2. root wrapper, daemon, and the library both import
install -m 0755 -o root -g root "$repo/bin/sudogate-run" /usr/local/sbin/sudogate-run
install -m 0755 -o root -g root "$repo/bin/sudogate-daemon" /usr/local/sbin/sudogate-daemon

install -d -m 0755 -o root -g root /usr/local/lib/sudogate
rm -rf /usr/local/lib/sudogate/sudogate
cp -r "$repo/sudogate" /usr/local/lib/sudogate/sudogate
find /usr/local/lib/sudogate/sudogate -name '__pycache__' -type d -prune -exec rm -rf {} +
chown -R root:root /usr/local/lib/sudogate
find /usr/local/lib/sudogate -type d -exec chmod 0755 {} +
find /usr/local/lib/sudogate -type f -exec chmod 0644 {} +

# 3. /etc/sudogate
install -d -m 0755 -o root -g root /etc/sudogate
install -m 0444 -o root -g root "$repo/config/destructive.patterns" /etc/sudogate/destructive.patterns

# 4. daemon config: the bot token moves out of the gated user's home, where
#    anything running as that user could read it.
user_config="${SUDOGATE_USER_CONFIG:-$target_home/.config/sudogate/config.json}"
if [ -f /etc/sudogate/config.json ]; then
  echo "Keeping the existing /etc/sudogate/config.json"
  tmp_config="$(mktemp)"
  cp /etc/sudogate/config.json "$tmp_config"
elif [ -f "$user_config" ]; then
  tmp_config="$(mktemp)"
  cp "$user_config" "$tmp_config"
  echo "Taking the bot configuration from $user_config"
else
  echo "No configuration found at $user_config. Run ~/bin/sudogate-bootstrap first." >&2
  exit 1
fi
python3 - "$tmp_config" "$target_user" "$target_uid" <<'PY'
import json, sys
path, user, uid = sys.argv[1], sys.argv[2], int(sys.argv[3])
cfg = json.loads(open(path).read())
cfg["gated_user"] = user
cfg["gated_uid"] = uid
open(path, "w").write(json.dumps(cfg, indent=2))
PY
install -m 0400 -o "$daemon_user" -g "$daemon_user" "$tmp_config" /etc/sudogate/config.json
rm -f "$tmp_config"

# 5. TOTP seed. Root-owned and root-only: the daemon cannot read it either,
#    so the code it carries is still checked by something it cannot forge.
if [ ! -f /etc/sudogate/seed ]; then
  if [ ! -f "$seed_tmp" ]; then
    echo "Missing $seed_tmp. Run this first:  ~/bin/sudogate-seed" >&2
    exit 1
  fi
  install -m 0400 -o root -g root "$seed_tmp" /etc/sudogate/seed
else
  echo "Keeping the existing /etc/sudogate/seed"
fi

# 6. optional policy: require a TOTP code for every command, not only
#    destructive ones. Root-owned, so neither the user nor the daemon can
#    clear it.
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

# 7. audit log
install -d -m 0755 -o root -g root /var/log/sudogate

# 8. sudoers rule, validated before install
tmp_sudoers="$(mktemp)"
sed "s/__USER__/$target_user/g" "$repo/config/sudogate.sudoers.template" > "$tmp_sudoers"
if ! visudo -c -f "$tmp_sudoers"; then
  echo "sudoers rule is invalid, nothing installed." >&2
  rm -f "$tmp_sudoers"
  exit 1
fi
install -m 0440 -o root -g root "$tmp_sudoers" /etc/sudoers.d/sudogate
rm -f "$tmp_sudoers"

# 9. system service. The per-user unit from earlier versions ran the daemon as
#    the gated account and is replaced, not kept alongside.
install -m 0644 -o root -g root "$repo/systemd/sudogate.service" /etc/systemd/system/sudogate.service
systemctl daemon-reload
systemctl enable sudogate.service
# restart, not just start: the daemon reads the TOTP policy and the pattern
# list once, at startup, so re-running this installer with a changed policy
# has to replace a daemon that is already up.
systemctl restart sudogate.service

echo
echo "Root half installed. The daemon runs as $daemon_user."
echo
if [ -f "$user_config" ]; then
  cat <<NOTE
  The bot token is now in /etc/sudogate/config.json (0400 $daemon_user).
  A copy is still at $user_config, readable by $target_user.
  Delete it:  shred -u "$user_config"

NOTE
fi
cat <<NOTE
  If you used an earlier version, stop the per-user daemon, which ran as
  $target_user:

    systemctl --user disable --now sudogate
    rm -f "$target_home/.config/systemd/user/sudogate.service"

  Then, as $target_user:  shred -u $seed_tmp
NOTE
