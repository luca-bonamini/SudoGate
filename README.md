# claude-telegram

Layer Telegram per Claude Code su `home-server`: notifiche in uscita, bot per richieste brevi e
gate di approvazione per i comandi `sudo`.

Design completo in [`docs/2026-09-11-telegram-gate-design.md`](docs/2026-09-11-telegram-gate-design.md).

Stato: piano 1 implementato e testato. Manca il bootstrap del bot, che richiede il telefono — vedi `docs/consegna-piano-1.md`.

## Dove finiscono i file

Il repo non è la posizione di esecuzione. L'installazione copia i file qui:

| dal repo | a |
|---|---|
| `ctg/` | `~/.local/lib/claude-telegram/ctg/` |
| `bin/claude-telegram` | `~/bin/` |
| `bin/claude-tg-hook` | `~/bin/` |
| `bin/ctg-bootstrap` | `~/bin/` |
| `systemd/claude-telegram.service` | `~/.config/systemd/user/` |

Installazione: `./install.sh`, idempotente.

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
