# sudogate

Approve Claude Code's privileged commands from Telegram, with a TOTP second factor on
destructive ones that only root can verify.

Claude cannot escalate privileges directly: a `PreToolUse` hook denies it and points at the
`sudogate` shim. The shim asks a dedicated Telegram bot for approval. You tap a button. For
commands matching a root-owned pattern list, the bot also asks for a 6-digit code, and a
root-owned wrapper verifies it against a seed your user account cannot read.

---

## Read this before installing

**sudogate raises the privilege available to Claude. It does not lower it.**

Before: the password prompt means Claude cannot run privileged commands at all.
After: Claude can run any command as root, provided you tap Approve on your phone.

Be concrete about what each half protects:

| threat | covered? |
|---|---|
| Claude acting unsupervised, or an automation mistake | yes — nothing runs without your tap |
| You being away from the terminal and missing a prompt | yes — the approval reaches your phone |
| Someone who controls your Telegram account | **no** for non-destructive commands; yes for destructive ones, which also need the authenticator |
| Someone who can already run code as your user | **no** for non-destructive commands; yes for destructive ones — the TOTP seed is `0400 root` and your user cannot read it |
| An obfuscated destructive command that evades the pattern list | **no** — pattern matching is best-effort defence in depth, not a proof |

So: for non-destructive commands, your user account becomes effectively equivalent to root,
gated by one tap. That is the deal. The TOTP factor is real, verified root-side, and covers the
destructive list only. Set `totp_always` to extend it to every command.

Install this only if that trade is worth it to you. If your goal is to *increase* the security
of a machine, this is the wrong tool.

---

## How it works

1. Claude runs `sudogate apt update` — the plain privileged form is denied by the hook.
2. The shim writes the command to a nonce-keyed state file and asks the daemon.
3. The daemon sends you a Telegram message with Approve / Deny.
4. On approve, the shim calls the root wrapper with the nonce.
5. The wrapper reads the command by nonce, **re-classifies** it against
   `/etc/sudogate/destructive.patterns` (`0444 root`), and if destructive requires a TOTP code
   checked against `/etc/sudogate/seed` (`0400 root`). Then it runs the command and appends to
   `/var/log/sudogate/audit.log`.

The wrapper trusts neither the destructive flag nor the pattern list on the user side, because
both are writable by your user. That re-classification is what makes the second factor hold
against code running as you.

Non-destructive commands approved once are cached for 8 hours, keyed on
`sha256(cwd + command)`, exact match only. Destructive commands are never cached.

The command never travels through Telegram, and the 64-byte callback payload carries only a
nonce. Telegram carries a vote and, when required, a code.

## Requirements

- Linux with systemd user units, Python 3.11+ (standard library only — no pip, no venv)
- `qrencode` for the TOTP QR (optional; otherwise the script prints an `otpauth://` URI)
- A Telegram account

## Install

### 1. Telegram bot

Create a bot with [@BotFather](https://t.me/BotFather) (`/newbot`) and **send it a message**. A
bot cannot write to a user who has not written to it first.

Use a bot dedicated to sudogate. Telegram's `getUpdates` allows a single reader per bot, so
sharing one with another tool will make both miss messages.

### 2. User half

```
git clone https://github.com/luca-bonamini/SudoGate
cd SudoGate
./install.sh
~/bin/sudogate-bootstrap     # bot token (hidden) + chat id
~/bin/sudogate-seed          # scan the QR with your authenticator
```

### 3. Root half

A malformed file in `/etc/sudoers.d/` can break privilege escalation for the whole machine, and
recovery means booting to a recovery shell.

**Open a second SSH session, confirm elevation works there, and leave it open.** The installer
validates with `visudo -c` before installing, but that session is your way back in.

Then, with elevated rights:

```
./install-root.sh
```

It installs the wrapper, `/etc/sudogate/{seed,destructive.patterns}`, the audit log directory,
and a sudoers rule scoped to the wrapper alone — never to a shell, never to `ALL`.

### 4. Finish

```
shred -u /tmp/sudogate-seed
systemctl --user enable --now sudogate
```

### 5. Register with Claude Code

As a plugin:

```
/plugin marketplace add luca-bonamini/SudoGate
/plugin install sudogate@sudogate
```

Then add the allowlist entry to `~/.claude/settings.json`, so the shim itself does not trigger a
second prompt on top of the Telegram one:

```json
"permissions": { "allow": ["Bash(sudogate:*)"] }
```

## Verify

| check | expected |
|---|---|
| `systemctl --user is-active sudogate` | `active` |
| `visudo -c` (as root) | `parsed OK` |
| reading `/etc/sudogate/seed` as your user | `Permission denied` |
| `sudogate id -un` | `root`, after one tap |
| a destructive command with a wrong code | denied, and **not executed** |

## Kill switch

```
systemctl --user stop sudogate
```

The gate fails closed: with no daemon, the shim denies everything. To revoke Claude's root
access entirely, remove `/etc/sudoers.d/sudogate`.

## Configuration

`~/.config/sudogate/config.json`, mode `0600`:

| key | default | meaning |
|---|---|---|
| `bot_token` | — | required |
| `chat_id` | — | the only chat allowed to approve |
| `approval_ttl_seconds` | 120 | how long an approval request stays open |
| `cache_ttl_seconds` | 28800 | how long an approved non-destructive command is remembered |
| `totp_always` | `false` | require TOTP for every command, not just destructive ones |
| `destructive_patterns` | see `sudogate/config.py` | user-side list, used only for the prompt |

The list that actually enforces is `/etc/sudogate/destructive.patterns`, root-owned. Editing the
user-side list changes what the bot asks for, never what the wrapper permits.

## Security notes

- The bot token is stored `0600`; error messages never include it, and exception chains are
  suppressed so the token cannot leak through a traceback.
- Nonces are single-use with a 120-second TTL, and are validated as filenames to rule out path
  traversal.
- Any Telegram update from a chat other than the configured one is discarded.
- The audit log is root-owned, so your user cannot erase evidence of what ran.
- The `PreToolUse` hook strips heredoc bodies before matching, so writing a document that
  *mentions* privileged commands is not mistaken for running one.

Found a hole? Open an issue. Please do not include a working exploit in a public report.

## Known limitations

- Pattern matching is heuristic. A determined obfuscation of a destructive command can evade the
  list and get through with a button tap alone.
- Single user per installation: the sudoers rule names one account.
- Linux only. There is no macOS path.

## Development

```
python3 -m unittest discover -s tests
```

112 tests, standard library only. The TOTP implementation is checked against the RFC 6238 test
vectors, and the enforcement path is tested as a subprocess: a destructive command with a wrong
code must be denied and must not run.

## License

MIT — see [LICENSE](LICENSE).
