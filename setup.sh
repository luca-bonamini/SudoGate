#!/usr/bin/env bash
# setup.sh - guided install of the sudogate user half.
# The root half stays separate and is run by hand: see the closing message.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

say "sudogate - guided install"
cat <<'WARN'
Before anything else, the trade in plain words:

  sudogate RAISES the privilege available to Claude. It does not lower it.
  Today the password prompt stops Claude from running privileged commands
  at all. Afterwards Claude can run any command as root, provided you tap
  Approve on your phone.

  For commands that are NOT destructive, anyone able to run code as your
  user reaches root through that tap. The TOTP second factor only covers
  commands matching the destructive pattern list.

  The approval itself runs under a separate system account, so code running
  as you cannot forge one. It still cannot tell a harmful command from a
  harmless one: only you can, when you read it on your phone.

Install only if that trade is worth it to you.
WARN
read -r -p $'\nProceed? [type yes] ' answer
[ "$answer" = "yes" ] || { echo "Aborted."; exit 1; }

say "1/4 - Checking requirements"
command -v python3 >/dev/null || { echo "python3 not found" >&2; exit 1; }
python3 - <<'PY'
import sys
if sys.version_info < (3, 11):
    sys.exit(f"Python 3.11+ required, found {sys.version.split()[0]}")
print("python3", sys.version.split()[0], "ok")
PY
command -v systemctl >/dev/null || echo "  warning: systemctl not found, start the daemon by hand"
command -v qrencode >/dev/null || echo "  warning: qrencode not found, the seed step prints a URI instead of a QR"

say "2/4 - Copying library and executables"
"$repo/install.sh"

say "3/4 - Telegram bot"
cat <<'BOT'
On Telegram, with @BotFather:
  /newbot  -> pick a name -> copy the token
Then OPEN the chat with the new bot and send it any message.
A bot cannot write to you until you have written to it.

Use a dedicated bot: getUpdates allows a single reader per bot.
BOT
read -r -p $'\nDone? Press Enter to continue with the token. ' _
"$HOME/bin/sudogate-bootstrap"

say "4/4 - TOTP seed"
echo "A QR is about to be shown: scan it with your authenticator app."
read -r -p "Press Enter when ready. " _
"$HOME/bin/sudogate-seed"

say "User half complete. The root half is yours to run."
cat <<ROOT

  A malformed file in /etc/sudoers.d/ can break privilege escalation for the
  whole machine. Open a SECOND SSH session, confirm elevation works there,
  and LEAVE IT OPEN.

Then, with root rights:

  $repo/install-root.sh

That step installs the daemon as its own system account, moves the bot token
to /etc/sudogate/config.json, and starts the service. Finally, remove the two
copies it no longer needs in your home:

  shred -u /tmp/sudogate-seed
  shred -u "$HOME/.config/sudogate/config.json"

ROOT
