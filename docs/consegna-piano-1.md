# Consegna del piano 1

Data: 11 settembre 2026

## Stato

I task da 1 a 11 sono implementati, testati e committati. La suite conta 82 test e passa.

| task | esito |
|---|---|
| 1 — loader di configurazione | fatto, 9 test |
| 2 — client Telegram | fatto, 9 test |
| 3 — etichetta di progetto | fatto, 9 test |
| 4 — estrazione dal transcript | fatto, 8 test |
| 5 — filtro anti-rumore | fatto, 12 test |
| 6 — canale IPC | fatto, 7 test |
| 7 — messaggi | fatto, 5 test |
| 8 — router del daemon | fatto, 10 test |
| 9 — entrypoint degli hook | fatto, 7 test |
| 10 — bootstrap | fatto, 6 test |
| 11 — unit e installer | fatto, installer eseguito due volte |
| 12 — registrazione hook e verifica | **da fare, richiede il telefono** |

Verifiche già eseguite:

- `./install.sh` è idempotente: due esecuzioni consecutive, nessun errore.
- Il daemon rifiuta di partire senza `config.json`. Il journal riporta
  `ctg.config.ConfigError: configurazione non leggibile`, che è il comportamento voluto.
- `claude-tg-hook` senza daemon esce `0` in 0,03 s.
- Il formato del transcript è stato verificato su un file reale in
  `~/.claude/projects/-home-luca-Project-MayBeCompany/`: `type: assistant`,
  `message.content[0].type: text`.

`~/.claude/settings.json` non è stato modificato. Gli hook non sono registrati, quindi al momento
il sistema è inerte.

## Cosa resta, in ordine

### 1. Creare il bot

Su Telegram, da BotFather: `/newbot`, nome a scelta, si ottiene un token della forma
`123456789:AA...`.

### 2. Bootstrap

```bash
~/bin/ctg-bootstrap
```

Chiede il token, che non viene mostrato a schermo. Poi attende: mandare `/start` al bot appena
creato. Scrive `~/.claude/telegram/config.json` con permessi `0600`.

Controllo:

```bash
ls -l ~/.claude/telegram/config.json    # atteso: -rw-------
```

### 3. Avviare il daemon

```bash
systemctl --user enable --now claude-telegram
systemctl --user status claude-telegram --no-pager | head -5
```

Atteso: `Active: active (running)`.

### 4. Provare il trasporto prima di toccare settings.json

```bash
cd ~/Project/personal/claude-telegram
PYTHONPATH=$PWD python3 - <<'PY'
import os, pathlib
from ctg import ipc
home = pathlib.Path.home() / ".claude" / "telegram"
print(ipc.request(home / "sock",
                  {"hook_event_name": "Notification", "cwd": os.getcwd(),
                   "message": "prova dal piano 1"}, timeout=5))
PY
```

Atteso: `{'sent': True, 'reason': 'inviato'}` e il messaggio arriva su Telegram.

Se non arriva, fermarsi qui. `settings.json` non va toccato finché il trasporto non funziona.

### 5. Registrare gli hook

Backup e kill switch prima della modifica:

```bash
cp ~/.claude/settings.json ~/.claude/settings.json.bak-$(date +%Y%m%d-%H%M%S)
touch ~/.claude/telegram/disabled
```

Aggiungere a `~/.claude/settings.json`, allo stesso livello di `"model"`:

```json
"hooks": {
  "Notification": [
    {"hooks": [{"type": "command", "command": "$HOME/bin/claude-tg-hook", "timeout": 5}]}
  ],
  "Stop": [
    {"hooks": [{"type": "command", "command": "$HOME/bin/claude-tg-hook", "timeout": 5}]}
  ],
  "UserPromptSubmit": [
    {"hooks": [{"type": "command", "command": "$HOME/bin/claude-tg-hook", "timeout": 5}]}
  ]
}
```

Validare:

```bash
python3 -c "import json;json.load(open('/home/luca/.claude/settings.json'));print('JSON valido')"
```

Se fallisce, ripristinare dal backup.

### 6. Disarmare e provare

```bash
rm ~/.claude/telegram/disabled
```

In una sessione nuova, per esempio `tmux attach -t rc-personal`:

1. Domanda che si risolve in pochi secondi. Atteso: **nessun** messaggio.
2. Lavoro che supera i 120 s. Atteso: `[personal] finito` con le ultime righe della risposta.
3. Richiesta di permesso. Atteso: `[<progetto>] permesso richiesto`.
4. `/stato` al bot. Atteso: uptime e lista delle sessioni tmux.

### 7. Sopravvivenza al reboot

```bash
systemctl --user is-enabled claude-telegram   # atteso: enabled
loginctl show-user luca --property=Linger     # atteso: Linger=yes
```

## Se qualcosa va storto

`touch ~/.claude/telegram/disabled` disarma tutti gli hook subito, senza modificare la
configurazione e senza riavviare nulla. Le sessioni Claude Code continuano a funzionare come
prima.

Per tornare indietro del tutto: rimuovere il blocco `"hooks"` da `settings.json` e
`systemctl --user disable --now claude-telegram`.
