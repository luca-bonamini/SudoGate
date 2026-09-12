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
> provided you tap Approve. For non-destructive commands, anyone who can run code as your user
> can reach root through that tap. The TOTP second factor only covers commands matching the
> destructive pattern list. Install this only if that trade is worth it to you.

Do not soften this and do not bury it after the instructions.

## Install

Two halves. The user runs the root half themselves; it needs their password.

1. **Telegram bot.** Ask them to create a bot with @BotFather (`/newbot`) and then send that bot
   a message. A bot cannot message a user who has not written to it first.
2. **User half:** `./install.sh` — copies the package to `~/.local/lib/sudogate`, the
   executables to `~/bin`, and the systemd user unit.
3. **Config:** `~/bin/sudogate-bootstrap` — asks for the bot token (hidden input), waits for a
   message, captures the chat id, writes `~/.config/sudogate/config.json` at `0600`.
4. **TOTP seed:** `~/bin/sudogate-seed` — prints the secret once and a QR. The user scans it with
   an authenticator app. Writes `/tmp/sudogate-seed`.
5. **Root half:** tell the user to open a **second SSH session with working privileges** and keep
   it open, then run the root installer with elevated rights: `install-root.sh`. A malformed file
   in `/etc/sudoers.d/` can break privilege escalation machine-wide; the installer validates with
   `visudo -c`, and that second session is the way back in.
6. `shred -u /tmp/sudogate-seed`, then `systemctl --user enable --now sudogate`.

Then verify with the checks under Diagnose.

## Diagnose

Run these and read the output before guessing:

| check | command | expected |
|---|---|---|
| daemon | `systemctl --user is-active sudogate` | `active` |
| socket | `ls -l ~/.config/sudogate/gate.sock` | exists, `srw-------` |
| config | `ls -l ~/.config/sudogate/config.json` | `-rw-------` |
| sudoers syntax | `visudo -c` (as root) | `parsed OK` |
| NOPASSWD | run `/usr/local/sbin/sudogate-run` with `-n` elevation | usage text, no password prompt |
| seed | read `/etc/sudogate/seed` as the user | `Permission denied` — this is correct |
| audit | `sudogate cat /var/log/sudogate/audit.log` | `RUN` / `DENY` lines |

Common failures:

- **Approval never arrives.** The daemon is down, or the bot token is wrong. Check
  `journalctl --user -u sudogate -n 20`.
- **Everything is denied with "gate irraggiungibile".** The daemon is not running. This is
  deliberate: the gate fails closed.
- **The wrapper asks for a password.** The sudoers file is missing or has permissions wider than
  `0440`; those are ignored silently.
- **A command ran without asking for TOTP and you expected one.** It did not match
  `/etc/sudogate/destructive.patterns`. That file is root-owned on purpose; adding a pattern
  needs root.

## Rotate the TOTP seed

Run `~/bin/sudogate-seed`, scan the new QR, then re-run the root installer. The old code stops
working immediately. Removing the authenticator entry without rotating locks out every
destructive command.

## Uninstall

```
systemctl --user disable --now sudogate
rm -f /etc/sudoers.d/sudogate /usr/local/sbin/sudogate-run     # as root
rm -rf /etc/sudogate /var/log/sudogate                          # as root
rm -rf ~/.local/lib/sudogate ~/.config/sudogate ~/bin/sudogate*
```

Removing `/etc/sudoers.d/sudogate` is the single step that revokes Claude's root access. Do that
first if the user is in a hurry.

## Known limitation: the hook reads the whole command string

The `PreToolUse` hook inspects the full Bash command text. Heredoc bodies are stripped before
matching, but a command that merely *mentions* privileged invocation inside an unusual quoting
construct can still be denied. If that happens, write the file with an editor tool instead of a
shell heredoc.
