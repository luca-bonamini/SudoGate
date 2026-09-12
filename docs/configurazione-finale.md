# Configurazione finale

Tutto il codice è scritto e testato (`python3 -m unittest discover -s tests`). Questa è
l'unica parte interattiva: due bot Telegram, un QR TOTP, una riga sudoers. Richiede il telefono
e, per la parte root, `sudo`.

Architettura ibrida:
- **ccgram** → notifiche, bot interattivo, approvazioni non-sudo. Bot #1.
- **gate** (questo repo) → tutto ciò che è sudo: bottone di approvazione per ogni `claude-sudo`,
  più TOTP sui comandi distruttivi. Bot #2.

Le due metà sono indipendenti. Si può fermare a metà: fare solo ccgram, e il gate dopo.

## Sicurezza, da leggere prima

Il gate alza il privilegio disponibile a Claude: oggi `sudo` chiede la password e Claude non lo
esegue; dopo, `claude-sudo` esegue come root previa approvazione su Telegram. Per i comandi **non**
distruttivi, l'utente `luca` diventa di fatto equivalente a root (basta un tap). Per i comandi
**distruttivi**, serve anche il TOTP, il cui seed è `root:root 0400` e viene verificato dal
wrapper root: `luca` non può calcolare un codice valido. Questo è il vero secondo fattore.

Chi controlla il tuo account Telegram può approvare i non-distruttivi. Chi controlla anche
l'authenticator approva i distruttivi. Interruttore d'emergenza: rimuovere il blocco `hooks` da
`~/.claude/settings.json`, oppure `systemctl --user stop ctg-gate` (senza daemon, `claude-sudo`
nega tutto).

## Parte 1 — ccgram (bot #1)

1. Su BotFather: `/newbot`, ottieni il token del bot #1.
2. Prendi il tuo `chat_id` da @userinfobot.
3. Wizard:
   ```
   ! ~/.npm-global/bin/ccgram setup
   ```
   Scrive `~/.ccgram/.env` e fonde i suoi hook in `~/.claude/settings.json`.
4. ccgram come unit `--user` (il suo `ccgram.service` upstream è system-level con sudo, non lo
   usiamo). Percorso del pacchetto installato:
   ```
   ! ls ~/.npm-global/lib/node_modules/@jsayubi/ccgram/dist/workspace-telegram-bot.js
   ```
   Unit:
   ```
   cat > ~/.config/systemd/user/ccgram.service <<'UNIT'
   [Unit]
   Description=CCGram - Claude Code Telegram Bot
   After=network-online.target

   [Service]
   Type=simple
   ExecStart=/usr/bin/node %h/.npm-global/lib/node_modules/@jsayubi/ccgram/dist/workspace-telegram-bot.js
   Restart=on-failure
   RestartSec=5

   [Install]
   WantedBy=default.target
   UNIT
   systemctl --user daemon-reload
   systemctl --user enable --now ccgram
   ```
5. Prova: in una sessione Claude, provoca una richiesta di permesso non-sudo. Deve arrivare su
   Telegram con i bottoni.

## Parte 2 — gate sudo (bot #2)

### 2a. Bot e chat_id del gate

1. Su BotFather: `/newbot` **diverso** dal #1 (es. `home-server-gate-bot`). Il gate deve avere il
   suo bot, perché `getUpdates` ammette un solo lettore per bot.
2. Parte utente dell'installazione:
   ```
   ! cd ~/Project/personal/claude-telegram && ./install-gate.sh
   ```
3. Token e `chat_id` del bot #2 in `~/.claude/telegram/config.json`:
   ```
   ! ~/bin/ctg-bootstrap
   ```
   Incolla il token del bot #2 (non viene mostrato), poi manda `/start` al bot #2.
   Verifica: `ls -l ~/.claude/telegram/config.json` deve dare `-rw-------`.

### 2b. Seed TOTP

```
! ~/bin/ctg-gate-seed
```
Mostra il segreto una volta e un QR: scansionalo con l'authenticator (Google Authenticator, Aegis,
1Password...). Scrive `/tmp/claude-gate-seed` (0600), che il passo root sposta in `/etc/claude-gate/seed`.

### 2c. Parte root

**Attenzione sudoers.** Un file rotto in `/etc/sudoers.d/` rompe `sudo` su tutta la macchina; il
recupero richiede un boot in recovery, cioè ~15 minuti di firmware Lenovo. `install-gate-root.sh`
valida con `visudo -c` prima di installare, ma **tieni aperta una seconda sessione SSH con `sudo`
già funzionante** durante il passo, per rimediare se qualcosa va storto.

```
! sudo ~/Project/personal/claude-telegram/install-gate-root.sh
```
Installa: wrapper in `/usr/local/sbin/claude-sudo-run`; `/etc/claude-gate/destructive.patterns`
(0444 root); `/etc/claude-gate/seed` (0400 root); `/var/log/claude-gate/`; `/etc/sudoers.d/claude-gate`
(0440, validato).

Poi cancella il seed temporaneo e avvia il daemon:
```
! shred -u /tmp/claude-gate-seed
! systemctl --user enable --now ctg-gate
```

### 2d. Hook e allowlist

Backup e kill switch:
```
! cp ~/.claude/settings.json ~/.claude/settings.json.bak-$(date +%Y%m%d-%H%M%S)
```

In `~/.claude/settings.json`, aggiungere alla sezione `hooks` (accanto a quelli di ccgram) un
hook `PreToolUse` con matcher `Bash`, e la allowlist per lo shim:

```json
"permissions": { "allow": ["Bash(claude-sudo:*)"] },
"hooks": {
  "PreToolUse": [
    { "matcher": "Bash",
      "hooks": [{ "type": "command", "command": "$HOME/bin/claude-tg-gate", "timeout": 5 }] }
  ]
}
```

Se ccgram ha già una voce `PreToolUse` (matcher `AskUserQuestion`), aggiungere la nostra come
elemento separato dell'array `PreToolUse`, senza toccare la sua.

Validare:
```
! python3 -c "import json;json.load(open('/home/luca/.claude/settings.json'));print('JSON valido')"
```

### 2e. Prova end-to-end

In una sessione Claude nuova:

1. Chiedi a Claude di eseguire `sudo apt update`. Atteso: l'hook lo **nega** e indica
   `claude-sudo apt update`.
2. `claude-sudo apt update`. Atteso: bottone Approva/Nega sul bot #2. Approva → gira, nessun
   prompt nell'app.
3. Di nuovo `claude-sudo apt update` entro 8h. Atteso: nessun bottone, esecuzione diretta (cache).
4. `claude-sudo rm -rf /tmp/prova-gate` (crea prima la dir). Atteso: Approva → il bot chiede le 6
   cifre → inserisci il codice → esegue. Con codice sbagliato: negato.
5. `cat /var/log/claude-gate/audit.log` (con sudo): righe `RUN` / `DENY`.

## Ripristino

- Disarmo rapido: `systemctl --user stop ctg-gate` (il gate nega tutto senza daemon).
- Rimozione hook: togliere il blocco `PreToolUse`/`claude-tg-gate` da `settings.json`.
- Rimozione totale root: `sudo rm /etc/sudoers.d/claude-gate /usr/local/sbin/claude-sudo-run`,
  `sudo rm -rf /etc/claude-gate /var/log/claude-gate`.
