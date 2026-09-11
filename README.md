# claude-telegram

Layer Telegram per Claude Code su `home-server`: notifiche in uscita, bot per richieste brevi e
gate di approvazione per i comandi `sudo`.

Design completo in [`docs/2026-09-11-telegram-gate-design.md`](docs/2026-09-11-telegram-gate-design.md).

Stato: spec approvata, implementazione non iniziata.

## Dove finiscono i file

Il repo non è la posizione di esecuzione. L'installazione copia i file qui:

| dal repo | a |
|---|---|
| `bin/claude-telegram.py` | `~/bin/` |
| `bin/claude-tg-notify.sh` | `~/bin/` |
| `bin/claude-tg-gate.sh` | `~/bin/` |
| `bin/claude-tg-mark.sh` | `~/bin/` |
| `bin/claude-sudo` | `~/bin/` |
| `bin/claude-sudo-run` | `/usr/local/sbin/` (root, `0755`) |
| `systemd/claude-telegram.service` | `~/.config/systemd/user/` |

Configurazione e stato stanno in `~/.claude/telegram/`, il seed TOTP in `/etc/claude-gate/seed`.
Nessuno dei due è nel repo.

## Segreti

Il repo non contiene token, `chat_id` né seed. Il `.gitignore` blocca i nomi dei file di
runtime, in caso una copia venga fatta qui per debug. Prima di ogni commit verificare che non
siano stati aggiunti.

## Test

```
python3 -m unittest discover -s tests
```

Dipendenze: solo standard library di Python 3.14.
