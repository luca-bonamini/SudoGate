---
name: sudogate
description: Set up, diagnose, or repair sudogate — the Telegram approval gate for sudo commands. Use when the user wants to install sudogate, connect a Telegram bot, rotate the TOTP seed, check why an approval is not arriving, or uninstall it.
---

# sudogate

A gate that stops Claude Code from running privileged commands unsupervised. Claude calls the
`sudogate` shim instead; the user approves from Telegram with a button, and destructive commands
additionally need a TOTP code that only root can verify.

## Before anything else: state the trade-off

Whenever the user asks to install sudogate, say this first, in one short paragraph, and get an
answer before installing:

> sudogate raises the privilege available to Claude. Today the password prompt means Claude
> cannot run privileged commands at all. After installation Claude can run any command as root,
> provided you tap Approve. The approval itself runs under a separate system account, so code
> running as your user cannot forge one — but for non-destructive commands it can still ask for
> one, and your tap is then the whole check. The TOTP second factor only covers commands
> matching the destructive pattern list. Install this only if that trade is worth it to you.

Do not soften this and do not bury it after the instructions.

## Install

Two halves. The user runs the root half themselves; it needs their password.

1. **Telegram bot.** Ask them to create a bot with @BotFather (`/newbot`) and then send that bot
   a message. A bot cannot message a user who has not written to it first.
2. **User half:** `./install.sh` — copies the package to `~/.local/lib/sudogate` and the shim,
   hook and setup helpers to `~/bin`. It also retires the per-user daemon unit from earlier
   versions, which ran the approval as the account being gated.
3. **Config:** `~/bin/sudogate-bootstrap` — asks for the bot token (hidden input), waits for a
   message, captures the chat id, writes `~/.config/sudogate/config.json` at `0600`. The root
   installer moves that file to `/etc/sudogate/config.json`.
4. **TOTP seed:** `~/bin/sudogate-seed` — prints the secret once and a QR. The user scans it with
   an authenticator app. Writes `/tmp/sudogate-seed`.
5. **Root half:** tell the user to open a **second SSH session with working privileges** and keep
   it open, then run the root installer with elevated rights: `install-root.sh`. A malformed file
   in `/etc/sudoers.d/` can break privilege escalation machine-wide; the installer validates with
   `visudo -c`, and that second session is the way back in. This step creates the `sudogate`
   system account, installs the library root-side, and starts the service.
6. `shred -u /tmp/sudogate-seed` and `shred -u ~/.config/sudogate/config.json` — the token now
   lives in `/etc/sudogate`, and the copy in the home directory is readable by the gated user.

**Ask about the policy at step 5.** If the user is going to reach for their authenticator
anyway, requiring a code for every command costs them nothing extra and closes the two gaps
the default leaves open: a compromised Telegram account, and code running as their user.
Install with `SUDOGATE_TOTP_ALWAYS=1` to enable it. Re-run with `0` to go back.

Then verify with the checks under Diagnose.

## Diagnose

Run these and read the output before guessing:

| check | command | expected |
|---|---|---|
| daemon | `systemctl is-active sudogate` | `active` |
| account | `systemctl show -p User sudogate` | `User=sudogate`, never the user's own account |
| socket | `ls -l /run/sudogate/gate.sock` | exists, `srw-rw-rw-` — the peer uid is checked, not the mode |
| records | `ls /run/sudogate/approved` as the user | `Permission denied` — this is correct |
| config | `ls -l /etc/sudogate/config.json` | `-r-------- sudogate sudogate` |
| library | `ls -ld /usr/local/lib/sudogate` | `drwxr-xr-x root root` |
| sudoers syntax | `visudo -c` (as root) | `parsed OK` |
| NOPASSWD | run `/usr/local/sbin/sudogate-run` with `-n` elevation | usage text, no password prompt |
| seed | read `/etc/sudogate/seed` as the user | `Permission denied` — this is correct |
| audit | `sudogate cat /var/log/sudogate/audit.log` | `RUN` / `DENY` lines |

Common failures:

- **Approval never arrives.** The daemon is down, or the bot token is wrong. Check
  `journalctl -u sudogate -n 20` with root rights.
- **The daemon refuses to start with "not the gated account".** `gated_uid` in
  `/etc/sudogate/config.json` does not match the account calling the shim. Re-run the root
  installer from that account.
- **The wrapper refuses to start.** It checks that `/usr/local/lib/sudogate` and `/etc/sudogate`
  are root-owned and not writable by anyone else, and that `/run/sudogate/approved` belongs to
  root or to the `sudogate` account. The message names the offending path.
- **Everything is denied with "gate unreachable".** The daemon is not running. This is
  deliberate: the gate fails closed.
- **The wrapper asks for a password.** The sudoers file is missing or has permissions wider than
  `0440`; those are ignored silently.
- **A command ran without asking for TOTP and you expected one.** It did not match
  `/etc/sudogate/destructive.patterns`. That file is root-owned on purpose; adding a pattern
  needs root.

## Change the policy

Enforcement lives in `/etc/sudogate/totp_always`, root-owned `0444`. Present means every
command needs a code; absent means only destructive ones do. Re-run the root installer with
`SUDOGATE_TOTP_ALWAYS=1` or `0`. The `totp_always` key in the user config only mirrors it for
the prompt: it can add friction, never remove it.

## Rotate the TOTP seed

Run `~/bin/sudogate-seed`, scan the new QR, then re-run the root installer. The old code stops
working immediately. Removing the authenticator entry without rotating locks out every
destructive command.

## Uninstall

```
# as root
systemctl disable --now sudogate
rm -f /etc/systemd/system/sudogate.service && systemctl daemon-reload
rm -f /etc/sudoers.d/sudogate /usr/local/sbin/sudogate-run /usr/local/sbin/sudogate-daemon
rm -rf /etc/sudogate /var/log/sudogate /var/lib/sudogate /usr/local/lib/sudogate
userdel sudogate

# as the user
rm -rf ~/.local/lib/sudogate ~/.config/sudogate ~/bin/sudogate*
```

Removing `/etc/sudoers.d/sudogate` is the single step that revokes Claude's root access. Do that
first if the user is in a hurry.

## Known limitation: the hook reads the whole command string

The `PreToolUse` hook inspects the full Bash command text. Heredoc bodies are stripped before
matching, but a command that merely *mentions* privileged invocation inside an unusual quoting
construct can still be denied. If that happens, write the file with an editor tool instead of a
shell heredoc.
