# SudoGate

**Let Claude Code run privileged commands — but only when you say so, from your phone.**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![Tests](https://img.shields.io/badge/tests-185%20passing-brightgreen)
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
  neither your user account nor the gate daemon can read the seed, so neither can forge a code.
- **You see what you approve.** The approval runs under its own system account, outside the one
  being gated. What the phone shows and what root runs are the same record, in a directory your
  agent cannot write.
- **Nothing to install but Python.** Standard library only. No pip, no venv, no daemon zoo.
- **Fails closed.** Daemon down, gate shut.

## How it works

```
  sudogate <cmd>                   the hook denies plain escalation and points here
        │                          runs as you
        ▼
  /run/sudogate/gate.sock          the kernel names the caller; another account is dropped here
        │
        ▼
  daemon                           runs as `sudogate`, not as you
        │                          classifies · asks Telegram · collects the code
        ├──▶ Telegram              Approve / Deny  ·  6 digits when destructive
        │
        ▼
  /run/sudogate/approved/<token>   0700 sudogate — you can neither read nor write it
        │
        ▼
  wrapper (root)                   re-classifies · verifies TOTP · runs · audits
```

**Three accounts, on purpose.** The shim runs as you and decides nothing. The daemon runs under
its own system account and decides everything: whether a command is destructive, whether it is
still in the approval cache, and what the phone is shown. Root only runs what the daemon
approved, after checking it again.

That split is what makes an approval mean something. The account the gate exists to constrain
cannot write an approval, cannot pre-fill the cache, and never handles the 6-digit code — the
code goes from Telegram into the approved record, which only root reads.

The wrapper never takes a command on its command line. It takes a token naming a record, and
classifies the command in it again using the root-owned pattern list. Telegram carries a vote
and, when required, a code — never the command.

Approved non-destructive commands are remembered for 8 hours in `/var/lib/sudogate/cache.json`,
keyed on `sha256(cwd + command)`, exact match only. Destructive ones are never cached.

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

That step creates the `sudogate` system account, moves the bot token to `/etc/sudogate` where
your user cannot read it, installs the wrapper and the library root-side, and starts the
service.

> **Before you run that:** this grants passwordless root to a wrapper your agent can call. In
> the default setup a single tap is enough for anything not on the destructive list. Read
> [Security](#security) first — it is short, and it is the part that decides whether this tool
> belongs on your machine.

Finally, remove the two copies now living in places the gate does not trust:

```bash
shred -u /tmp/sudogate-seed
shred -u ~/.config/sudogate/config.json
```

**Upgrading from a version before the daemon moved:** `install.sh` retires the per-user unit,
which ran the approval as the account being gated. Confirm nothing is left behind with
`systemctl --user status sudogate`.

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

Linux with systemd · Python 3.11+ · root rights for the install · a Telegram account ·
`qrencode` (optional, for the QR)

## Verify

| check | expected |
|---|---|
| `systemctl is-active sudogate` | `active` |
| `systemctl show -p User sudogate` | `User=sudogate` — not your account |
| `visudo -c` (as root) | `parsed OK` |
| reading `/etc/sudogate/seed` as your user | `Permission denied` |
| reading `/etc/sudogate/config.json` as your user | `Permission denied` |
| `ls /run/sudogate/approved` as your user | `Permission denied` |
| `sudogate id -un` | `root`, after one tap |
| a destructive command with a wrong code | denied, and **not executed** |

## Kill switch

```bash
sudo systemctl stop sudogate        # gate shut: the shim denies everything
sudo rm /etc/sudoers.d/sudogate     # revokes root access entirely
```

## Configuration

`/etc/sudogate/config.json`, mode `0400`, owned by the `sudogate` account. Your user cannot read
it, and the bot token lives there rather than in your home:

| key | default | meaning |
|---|---|---|
| `bot_token` | — | required |
| `chat_id` | — | the only chat allowed to approve |
| `approval_ttl_seconds` | 120 | how long a request stays open |
| `cache_ttl_seconds` | 28800 | how long an approved non-destructive command is remembered |
| `totp_always` | `false` | ask for a code every time — mirrors the policy below; can add friction, never remove it |
| `destructive_patterns` | see `sudogate/config.py` | fallback when `/etc/sudogate/destructive.patterns` is unreadable |
| `gated_user` / `gated_uid` | set by the installer | the single account the daemon answers |

Edit it with root rights and restart the service. What enforces lives in `/etc/sudogate`, owned
by root:

| path | mode | meaning |
|---|---|---|
| `destructive.patterns` | `0444` | the list the daemon and the wrapper classify against |
| `seed` | `0400` | the TOTP secret; neither your user nor the daemon can read it |
| `totp_always` | `0444` | if present, every command needs a code |
| `config.json` | `0400 sudogate` | the bot token and the gated account |

The code that enforces all three is root-owned too, at `/usr/local/lib/sudogate`, installed by
the root half. The wrapper refuses to start if that directory, anything above it, or any source
file inside it is writable by someone other than root — otherwise the enforcement could be
rewritten by the account it is meant to constrain.

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
| code already running as your user, forging an approval | yes — it cannot write one, and cannot read a token |
| code already running as your user, asking for one | **no** by default for non-destructive commands — the tap is the whole check; yes with `SUDOGATE_TOTP_ALWAYS=1` |
| an obfuscated destructive command that dodges the pattern list | **no** — matching is defence in depth, not proof |

So in the default configuration, for non-destructive commands your user account is effectively
equivalent to root, gated by one tap. That is the trade. What the gate guarantees is that the
tap happened and that you saw the command; it cannot tell you whether the command deserved it.

**If you are reaching for your authenticator anyway, require the code for everything.** Install
with `SUDOGATE_TOTP_ALWAYS=1`. Every command then needs the app in your hand, and the pattern
list stops being the thing that decides what is dangerous.

### What the gate authenticates, and what it does not

The approval runs under the `sudogate` system account. Your user — and so your agent — cannot
write an approved record, cannot read a token, cannot pre-fill the approval cache, and never
handles the 6-digit code. So a request that reaches root is one you were shown and approved.

What remains outside that guarantee:

- **The pattern list is a list of spellings, not of effects.** `python3 -c`, `perl -e`, or a
  heredoc written now and run later match nothing, so they are classified as harmless and, by
  default, need no code. `SUDOGATE_TOTP_ALWAYS=1` removes the list from the decision entirely.
- **Approval is judgement, not verification.** You are shown the exact command; nothing checks
  what it will do.
- **The 8-hour cache trades a tap for convenience.** An approved non-destructive command in the
  same directory runs again without asking. Set `cache_ttl_seconds` to `0` to turn that off.
- **Root runs the command through a shell**, with root's environment, and your agent chose the
  string. Approving `apt update` approves exactly that; approving something longer approves
  everything in it.

If your goal is to *increase* the security of a machine, this is still the wrong tool. It buys
supervision, not hardening.

The earlier design put the approval, the state directory and the bot token in the gated user's
own home, where anything running as that user could forge an approval outright. That was
[#1](https://github.com/luca-bonamini/SudoGate/issues/1), and it is what the three-account split
above exists to fix.

### Implementation notes

- The bot token is `0400` under the daemon's account; errors never include it, and exception
  chains are suppressed so it cannot surface in a traceback.
- The socket identifies its caller with `SO_PEERCRED`, which the kernel fills in. A request from
  any account but the gated one is dropped before it can reach your phone.
- Approval tokens are single-use, 300-second TTL, validated as filenames to rule out path
  traversal, and bound to the uid that asked for them.
- The wrapper imports from `/usr/local/lib/sudogate` and refuses to start unless that directory,
  everything above it, and every source file inside it are root-owned and root-writable only.
  Its policy paths are compile-time constants, not environment variables.
- Updates from any chat other than the configured one are dropped.
- The audit log is root-owned: your user cannot erase what ran.
- The hook strips heredoc bodies before matching, so writing a document that *mentions*
  privileged commands is not mistaken for running one.

Found a hole? Open an issue — without a working exploit in the public report, please.

## Limitations

- Pattern matching is heuristic; a determined obfuscation can slip past the list.
- One user per installation: the sudoers rule and the daemon both name a single account.
- Linux with systemd only. The daemon needs a system unit, a runtime directory and a state
  directory.

## Development

```bash
python3 -m unittest discover -s tests
```

185 tests, standard library only. TOTP is checked against the RFC 6238 vectors, and the
enforcement path is exercised end to end — shim, socket, daemon, record, wrapper — with the
real wrapper in a subprocess: a destructive command with a wrong code must be denied and must
not run, and a shim claiming a command is harmless must change nothing.

## License

MIT — see [LICENSE](LICENSE).
