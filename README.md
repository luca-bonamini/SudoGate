# SudoGate

**Let Claude Code run privileged commands — but only when you say so, from your phone.**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![Tests](https://img.shields.io/badge/tests-125%20passing-brightgreen)
![Dependencies](https://img.shields.io/badge/dependencies-none-lightgrey)

Claude asks. Your phone buzzes. You tap. It runs.

For anything destructive, a tap is not enough: you also send a 6-digit code from your
authenticator, and a root-owned wrapper checks it against a seed your own account cannot read.

```
Claude ▸  sudogate systemctl restart nginx

   📱  [webapp] privileged command
       systemctl restart nginx
       [ Approve ]  [ Deny ]

Claude ▸  done — nginx restarted
```

Leave your terminal. Leave the house. Your agent keeps working, and nothing touches root without
you.

---

## Why

Agents are useful right up to the moment they need `sudo`. Then you either stand guard at the
terminal, or you hand over a passwordless blank cheque and hope.

SudoGate is the third option: the agent proposes, you dispose — from wherever you are.

- **One tap.** No SSH, no terminal, no password typed on a phone keyboard.
- **A real second factor.** Destructive commands need TOTP, verified by root. Not a checkbox:
  your user account cannot read the seed, so it cannot forge the code.
- **You see what you approve.** The message is composed from the recorded command, not from
  anything the agent says.
- **Nothing to install but Python.** Standard library only. No pip, no venv, no daemon zoo.
- **Fails closed.** Daemon down, gate shut.

## How it works

```
  sudogate <cmd>          the hook denies plain escalation and points here
        │
        ▼
  shim ──▶ state file (nonce)      the command is recorded before you are asked
        │
        ▼
  daemon ──▶ Telegram              Approve / Deny  ·  6 digits when destructive
        │
        ▼
  wrapper (root)                   re-classifies · verifies TOTP · runs · audits
```

The wrapper never takes a command on its command line. It reads the one recorded for the nonce,
classifies it again using a root-owned pattern list, and only then runs it. Telegram carries a
vote and, when required, a code — never the command.

Approved non-destructive commands are remembered for 8 hours, keyed on `sha256(cwd + command)`,
exact match only. Destructive ones are never cached.

## Install

Two halves: one as you, one as root.

```bash
git clone https://github.com/luca-bonamini/SudoGate
cd SudoGate
./setup.sh
```

`setup.sh` walks you through the bot, the config, and the TOTP QR. Then, with root rights:

```bash
./install-root.sh          # add SUDOGATE_TOTP_ALWAYS=1 to require a code for everything
```

> **Before you run that:** this grants passwordless root to a wrapper your agent can call. In
> the default setup a single tap is enough for anything not on the destructive list. Read
> [Security](#security) first — it is short, and it is the part that decides whether this tool
> belongs on your machine.

Finally:

```bash
shred -u /tmp/sudogate-seed
systemctl --user enable --now sudogate
```

### Telegram bot

Create one with [@BotFather](https://t.me/BotFather) (`/newbot`) and send it a message — a bot
cannot write to you first. Give SudoGate a bot of its own: `getUpdates` allows one reader per
bot.

### Register with Claude Code

```
/plugin marketplace add luca-bonamini/SudoGate
/plugin install sudogate@sudogate
```

Then, so the shim itself does not prompt on top of the Telegram approval:

```json
"permissions": { "allow": ["Bash(sudogate:*)"] }
```

## Requirements

Linux with systemd user units · Python 3.11+ · a Telegram account · `qrencode` (optional, for
the QR)

## Verify

| check | expected |
|---|---|
| `systemctl --user is-active sudogate` | `active` |
| `visudo -c` (as root) | `parsed OK` |
| reading `/etc/sudogate/seed` as your user | `Permission denied` |
| `sudogate id -un` | `root`, after one tap |
| a destructive command with a wrong code | denied, and **not executed** |

## Kill switch

```bash
systemctl --user stop sudogate      # gate shut: the shim denies everything
rm /etc/sudoers.d/sudogate          # as root: revokes root access entirely
```

## Configuration

`~/.config/sudogate/config.json`, mode `0600`:

| key | default | meaning |
|---|---|---|
| `bot_token` | — | required |
| `chat_id` | — | the only chat allowed to approve |
| `approval_ttl_seconds` | 120 | how long a request stays open |
| `cache_ttl_seconds` | 28800 | how long an approved non-destructive command is remembered |
| `totp_always` | `false` | ask for a code every time — mirrors the policy below; can add friction, never remove it |
| `destructive_patterns` | see `sudogate/config.py` | decides what the bot asks for |

Anything under `~/.config` is writable by your user, so none of it enforces anything. What
enforces lives in `/etc/sudogate`, owned by root:

| path | mode | meaning |
|---|---|---|
| `destructive.patterns` | `0444` | the list the wrapper classifies against |
| `seed` | `0400` | the TOTP secret; your user cannot read it |
| `totp_always` | `0444` | if present, every command needs a code |

Change the policy by re-running the root installer with `SUDOGATE_TOTP_ALWAYS=1` (or `0`).

## Security

Worth three minutes before you install.

**SudoGate raises the privilege available to your agent. It does not lower it.** Before: the
password prompt stops Claude from running privileged commands at all. After: Claude can run
anything as root, provided you approve.

| threat | covered? |
|---|---|
| the agent acting unsupervised, or an automation mistake | yes — nothing runs without your approval |
| you being away and missing a terminal prompt | yes — the request reaches your phone |
| someone controlling your Telegram account | **no** by default for non-destructive commands; yes with `SUDOGATE_TOTP_ALWAYS=1` |
| someone already running code as your user | **no** by default for non-destructive commands; yes with `SUDOGATE_TOTP_ALWAYS=1` — the seed is `0400 root` |
| an obfuscated destructive command that dodges the pattern list | **no** — matching is defence in depth, not proof |

So in the default configuration, for non-destructive commands your user account is effectively
equivalent to root, gated by one tap. That is the trade.

**If you are reaching for your authenticator anyway, require the code for everything.** Install
with `SUDOGATE_TOTP_ALWAYS=1` and the two *no* rows become *yes*: no path from your user, or from
a stolen Telegram account, reaches root without the app in your hand. Same gesture, no weak half.

If your goal is to *increase* the security of a machine, this is the wrong tool. It buys
supervision, not hardening.

### Implementation notes

- The token is stored `0600`; errors never include it, and exception chains are suppressed so it
  cannot surface in a traceback.
- Nonces are single-use, 120-second TTL, validated as filenames to rule out path traversal.
- Updates from any chat other than the configured one are dropped.
- The audit log is root-owned: your user cannot erase what ran.
- The hook strips heredoc bodies before matching, so writing a document that *mentions*
  privileged commands is not mistaken for running one.

Found a hole? Open an issue — without a working exploit in the public report, please.

## Limitations

- Pattern matching is heuristic; a determined obfuscation can slip past the list.
- One user per installation: the sudoers rule names a single account.
- Linux only.

## Development

```bash
python3 -m unittest discover -s tests
```

125 tests, standard library only. TOTP is checked against the RFC 6238 vectors, and the
enforcement path runs as a subprocess: a destructive command with a wrong code must be denied
and must not run.

## License

MIT — see [LICENSE](LICENSE).
