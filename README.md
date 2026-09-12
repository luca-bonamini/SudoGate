# claude-telegram

Gate sudo su Telegram per Claude Code su `home-server`, con conferma TOTP sui comandi distruttivi.

Parte di un'architettura ibrida:
- **ccgram** (`@jsayubi/ccgram`, esterno) → notifiche, bot interattivo, approvazioni non-sudo.
- **questo repo** → tutto ciò che è sudo: bottone di approvazione per ogni `claude-sudo`, più
  TOTP sui comandi distruttivi, con seed verificato root-side.

Design: [`docs/2026-09-11-telegram-gate-design.md`](docs/2026-09-11-telegram-gate-design.md).
Configurazione (passi col telefono e root): [`docs/configurazione-finale.md`](docs/configurazione-finale.md).

Stato: codice completo e testato (103 test). Manca la configurazione interattiva.

## Come funziona

1. Claude non può usare `sudo` diretto: l'hook `PreToolUse` (matcher `Bash`) lo nega e impone
   `claude-sudo <comando>`.
2. Lo shim `claude-sudo` (utente) chiede approvazione al daemon del gate, che manda un bottone su
   un bot Telegram dedicato. Sui comandi distruttivi il bot chiede poi le 6 cifre TOTP.
3. Il wrapper `claude-sudo-run` (root, via `sudoers` NOPASSWD) legge il comando dallo state per
   nonce, **ri-classifica** il comando con pattern root-only, e sui distruttivi verifica il TOTP
   contro il seed root-only prima di eseguire. Così `luca` non aggira il secondo fattore.
4. I comandi non distruttivi già approvati saltano il bottone per 8h (cache su `sha256(cwd+comando)`).

## Moduli

| modulo | ruolo |
|---|---|
| `ctg/config.py` | loader configurazione + pattern distruttivi |
| `ctg/telegram.py` | client Bot API su urllib |
| `ctg/ipc.py` | socket unix shim ↔ daemon |
| `ctg/totp.py` | TOTP RFC 6238 |
| `ctg/gate.py` | classificazione sudo / distruttivo |
| `ctg/state.py` | store dei comandi in attesa, per nonce |
| `ctg/cache.py` | cache approvazioni |
| `ctg/wrapper.py` | autorizzazione root-side |
| `ctg/gatedaemon.py` | interazione di approvazione (bottoni + TOTP) |
| `ctg/sessions.py` | etichetta di progetto dal cwd |
| `ctg/bootstrap.py` | cattura token + chat_id |

| eseguibile | dove gira |
|---|---|
| `bin/claude-sudo` | utente, shim |
| `bin/claude-sudo-run` | root, wrapper |
| `bin/ctg-gate` | utente, daemon |
| `bin/claude-tg-gate` | hook PreToolUse |
| `bin/ctg-gate-seed` | utente, genera seed + QR |
| `bin/ctg-bootstrap` | utente, token + chat_id |

## Installazione

Utente: `./install-gate.sh` → copia lib, shim, daemon, hook e unit.
Root: `sudo ./install-gate-root.sh` → wrapper, `/etc/claude-gate`, sudoers validato.

Dettaglio e ordine in `docs/configurazione-finale.md`.

## Segreti

Mai nel repo. Token e chat_id in `~/.claude/telegram/config.json` (0600). Seed TOTP in
`/etc/claude-gate/seed` (0400 root), letto solo dal wrapper. `.gitignore` blocca i nomi dei file
di runtime.

## Test

```
python3 -m unittest discover -s tests
```
Solo standard library di Python 3.14.
