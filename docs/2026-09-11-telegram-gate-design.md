# Layer Telegram su home-server — design

Data: 11 settembre 2026
Stato: approvato in brainstorming, non implementato

## Scopo

Tre funzioni su un unico bot Telegram:

1. Notifiche in uscita da Claude Code quando serve un permesso o quando finisce un lavoro lungo.
2. Bot in ingresso per mandare richieste brevi alle sessioni Claude Code e per farsi inviare file.
3. Gate di approvazione fuori banda per i comandi `sudo`, con TOTP sui comandi distruttivi.

## Portata

Vale per ogni sessione `claude` su `home-server`, non per un singolo progetto. Gli hook sono
registrati in `~/.claude/settings.json`, quindi coprono le cinque sessioni Remote Control attuali,
quelle aggiunte in futuro e le sessioni lanciate a mano da SSH. Nessun progetto deve configurare
nulla.

L'identità del progetto arriva dal payload dell'hook, non dal path del file di configurazione:
ogni hook riceve su stdin un JSON con `cwd`, `session_id` e `transcript_path`. Il daemon mappa
`cwd` sul nome della tmux `rc-*` corrispondente; se non ce n'è una, usa il basename della
directory.

## Decisioni prese

| tema | decisione |
|---|---|
| architettura | daemon unico + hook sottili (opzione A) |
| ruolo di Telegram | sveglia e comandi rapidi; l'app Claude resta il posto dove si lavora |
| ampiezza sudo | wrapper generico con approvazione, non whitelist di comandi |
| TOTP | solo sui comandi che matchano la lista dei distruttivi |
| eventi notificati | richiesta di permesso, task finito o sessione idle |
| doppio prompt | eliminato con una regola `permissions.allow` sullo shim |
| memoria approvazioni | cache su match esatto, TTL configurabile, default 8 ore |
| trasporto | long-polling, niente webhook, niente esposizione su internet |

## Modello di fiducia

Il daemon gira come utente `luca` e il wrapper `sudo` si fida del daemon. Chi esegue codice come
`luca` può quindi fabbricare un'approvazione e ottenere root, per tutti i comandi che non
rientrano nella lista dei distruttivi.

Il gate protegge da due cose: azioni non supervisionate di Claude Code ed errori di automazione.
Non protegge da un attaccante che ha già esecuzione sull'utente.

I comandi distruttivi sono l'eccezione. Il seed TOTP sta in `/etc/claude-gate/seed` con permessi
`0400 root:root` e la verifica la esegue il wrapper, non il daemon. L'utente `luca` non può
leggere il seed né calcolare un codice valido. Per quei comandi serve l'authenticator sul
telefono.

La chiave di configurazione `totp_always` (default `false`) estende la richiesta di TOTP a ogni
`sudo`. Attivandola, non esiste più alcun percorso da `luca` a root senza il telefono.

Il bot interattivo e il gate condividono lo stesso account Telegram. Chi controlla quell'account
può mandare una richiesta a Claude Code e poi approvarla. Il TOTP è ciò che interrompe questa
catena per i comandi distruttivi.

## Componenti

| path | ruolo |
|---|---|
| `~/bin/claude-telegram.py` | daemon: long-polling, bottoni inline, router sessioni, cache |
| `~/bin/claude-tg-notify.sh` | hook `Notification` e `Stop`, non bloccante |
| `~/bin/claude-tg-gate.sh` | hook `PreToolUse` su `Bash`, nega l'uso diretto di `sudo` |
| `~/bin/claude-tg-mark.sh` | hook `UserPromptSubmit`, registra `t0` per sessione |
| `~/bin/claude-sudo` | shim che Claude Code invoca al posto di `sudo` |
| `~/.config/systemd/user/claude-telegram.service` | unit utente, `WantedBy=default.target` |
| `~/.claude/telegram/config.json` | `0600`: token, `chat_id`, soglie, pattern |
| `~/.claude/telegram/state/<nonce>.json` | richieste pendenti, TTL 120 s |
| `~/.claude/telegram/cache.json` | approvazioni ricordate |
| `~/.claude/telegram/audit.log` | append-only |
| `~/.claude/telegram/sock` | socket unix `0600`, hook verso daemon |
| `~/.claude/telegram/disabled` | se esiste, tutti gli hook escono subito con `0` |
| `/usr/local/sbin/claude-sudo-run` | wrapper eseguito come root |
| `/etc/sudoers.d/claude-gate` | riga `NOPASSWD` sul solo wrapper |
| `/etc/claude-gate/seed` | `0400 root:root`, seed TOTP |

Dipendenze: solo la standard library di Python 3.14 (`urllib`, `hmac`, `hashlib`, `base64`,
`socket`, `json`, `secrets`). Nessun pacchetto da installare, nessun venv.

Niente di tutto questo sta dentro i repo di progetto. `~/bin` e `_infra` non sono sotto git.

### Concorrenza

Il daemon è a thread singolo con una coda di lavoro. È l'unico lettore di `getUpdates`, che
ammette un solo consumer per bot. Gli hook non contattano mai `api.telegram.org`.

### Comportamento a daemon fermo

`claude-tg-notify.sh` e `claude-tg-mark.sh` escono `0` in silenzio: una notifica persa non deve
bloccare il lavoro. `claude-sudo` nega, perché non riceve alcun verdetto. `claude-tg-gate.sh` non dipende dal
daemon e continua a bloccare `sudo` diretto. Fail-closed sul privilegio, fail-open sulla
notifica.

## Gate sudo

### Divisione dei ruoli

L'approvazione avviene in un solo punto, lo shim. L'hook ha il compito separato di impedire che
`sudo` venga invocato scavalcando lo shim.

`~/bin/claude-sudo <comando>` è l'unica via con cui Claude Code esegue comandi privilegiati.
Gestisce nonce, dialogo con il daemon, attesa del verdetto e chiamata al wrapper.

`claude-tg-gate.sh`, hook `PreToolUse` con matcher `Bash`, legge `tool_input.command` e cerca
`sudo` in posizione di comando con la regex `(^|[;&|(]\s*)sudo\b`, escludendo la chiamata
interna dello shim al wrapper. Senza match esce `0` in circa 3 ms. Con match risponde:

```json
{"hookSpecificOutput":{"hookEventName":"PreToolUse",
 "permissionDecision":"deny","permissionDecisionReason":"usa claude-sudo <comando>"}}
```

L'hook non approva nulla e non attende mai il daemon.

### Sequenza

1. Lo shim genera un nonce con `secrets.token_urlsafe(16)` e scrive `state/<nonce>.json` con
   comando, `cwd`, etichetta della sessione e timestamp.
2. Lo shim si blocca in lettura sul socket unix, timeout 120 s.
3. Il daemon invia il messaggio: progetto, comando in blocco `code`, bottoni `Approva` e `Nega`
   con `callback_data` `a:<nonce>` e `n:<nonce>`, sotto il limite di 64 byte.
4. Alla callback il daemon verifica che `chat_id` sia in allowlist, che il nonce esista, non sia
   scaduto e non sia già stato usato. Lo marca usato.
5. Se il comando matcha la lista dei distruttivi, il bot chiede le sei cifre e attende un
   messaggio di testo. Altrimenti approva direttamente.
6. Il daemon scrive il verdetto sul socket. Lo shim esegue
   `sudo /usr/local/sbin/claude-sudo-run <nonce> [<codice>]`.
7. Il wrapper rilegge il comando da `state/<nonce>.json`, verifica il TOTP quando richiesto, ed
   esegue. Scrive una riga in `audit.log`.

Il comando non transita mai per Telegram né per la riga di comando del wrapper. Telegram
trasporta un voto e, quando serve, un codice.

### Assenza di doppio prompt

`~/.claude/settings.json` deve contenere:

```json
"permissions": {"allow": ["Bash(claude-sudo:*)"]}
```

Senza questa riga l'app chiederebbe il permesso di eseguire lo shim, prima che lo shim possa
chiedere il permesso su Telegram. Con la riga, l'unica approvazione è il tap su Telegram.

La regola copre le chiamate a `claude-sudo`. `Write`, `Edit`, `WebFetch` e gli altri tool
continuano a seguire il flusso di permessi attuale.

### Comandi distruttivi

Pattern in configurazione, modificabili senza toccare il codice:

`rm -rf`, `dd`, `mkfs`, `fdisk`, `parted`, `shutdown`, `reboot`, `poweroff`, `passwd`, `usermod`,
`useradd`, `visudo`, `sudoers`, `/etc/netplan`, `chown -R` e `chmod -R` su path di sistema,
`iptables`, `ufw`, `systemctl disable`, `systemctl mask`, `apt remove`, `apt purge`, pipe verso
shell (`curl ... | sh`), redirezioni su `/dev/sd*`, `tailscale down`.

### Cache delle approvazioni

Chiave: `sha256(cwd + "\0" + comando)`. Il `cwd` entra nella chiave perché un comando con path
relativi fa cose diverse in directory diverse.

TTL default 8 ore, in `config.json`. Il match è sulla stringa esatta, mai su prefisso.

I comandi distruttivi non entrano mai in cache: ricordarli per otto ore annullerebbe il TOTP.

`cache.json` è scritto e letto da `luca`, quindi è falsificabile da chi esegue codice come
`luca`. Questo non cambia il modello di fiducia descritto sopra, che già concede root a `luca`
per i comandi non distruttivi.

## Notifiche

| hook | comportamento |
|---|---|
| `Notification` | invia sempre |
| `UserPromptSubmit` | muto, registra `t0` per `session_id` |
| `Stop` | invia solo se il turno è durato più di 120 s, oppure se la richiesta veniva da Telegram |

Senza il filtro su `Stop` arriverebbe un messaggio per ogni risposta di Claude Code in ognuna
delle cinque sessioni, incluse quelle in cui si sta già chattando dall'app. La soglia è in
configurazione.

Su `Stop` il daemon legge la coda di `transcript_path`, estrae l'ultimo messaggio assistant e lo
tronca a 600 caratteri.

`claude-tg-notify.sh` gira sotto `timeout 2`.

## Bot interattivo

| comando | effetto |
|---|---|
| `/sessioni` | elenca le tmux `rc-*` vive con la directory di ciascuna |
| `/s <nome>` | imposta la sessione corrente, persistita nello stato del daemon |
| testo libero | inviato alla sessione corrente |
| `/file <path>` | `sendDocument` del file |
| `/stato` | uptime del daemon, sessione corrente, approvazioni pendenti |

Iniezione: `tmux send-keys -t rc-<nome> -l -- '<testo>'` seguito da
`tmux send-keys -t rc-<nome> Enter`. Il flag `-l` è necessario perché senza di esso una stringa
come `C-c` verrebbe interpretata come sequenza di tasti. I newline nel testo diventano spazi.

Le sessioni sono scoperte con `tmux ls` a ogni richiesta.

`sendDocument` ha un limite di 50 MB lato API. Sono rifiutati:
`~/.claude/.credentials.json`, `~/.claude/telegram/config.json`, `~/.ssh/id_*`, `/etc/shadow`,
`/etc/claude-gate/*`. Ogni invio finisce in `audit.log`.

Ogni update, messaggio o callback, viene scartato se `chat_id` non corrisponde a quello in
configurazione.

## Segreti

| segreto | path | permessi | chi lo legge |
|---|---|---|---|
| token del bot | `~/.claude/telegram/config.json` | `0600 luca` | daemon |
| `chat_id` | stesso file | `0600 luca` | daemon |
| seed TOTP | `/etc/claude-gate/seed` | `0400 root` | wrapper |

Il seed non compare in `config.json` e il daemon non lo legge. Il seed viene mostrato a schermo
una volta durante il bootstrap e non è scritto in alcun log.

Rotazione del token: `/revoke` su BotFather, poi aggiornamento di `config.json` e riavvio
dell'unit.

## Installazione

Passi che richiedono il telefono o root, quindi eseguiti dall'utente:

1. BotFather, `/newbot`, raccolta del token.
2. `/start` al bot, così il daemon in modalità bootstrap cattura il `chat_id`.
3. Scansione del QR TOTP, reso con `qrencode -t ANSI` se presente, altrimenti stampa dell'URI
   `otpauth://` da inserire a mano nell'authenticator.
4. Installazione di wrapper e sudoers, secondo la procedura sotto.

Passi eseguiti da Claude Code: scrittura dei file, generazione del seed, registrazione degli hook
in `~/.claude/settings.json`, abilitazione dell'unit con `systemctl --user enable --now
claude-telegram`.

### Procedura per sudoers

Un file malformato in `/etc/sudoers.d/` rende `sudo` inutilizzabile su tutta la macchina. Il
recupero richiede un boot in recovery, che su questo hardware significa circa quindici minuti di
attesa sul firmware Lenovo.

Ordine vincolato:

1. Il file viene scritto in `/tmp`, mai direttamente in `/etc/sudoers.d/`.
2. Validazione: `visudo -c -f /tmp/claude-gate`, che deve rispondere `parsed OK`.
3. Installazione:
   `sudo install -m 0440 -o root -g root /tmp/claude-gate /etc/sudoers.d/claude-gate`.
4. Durante tutta la verifica va tenuta aperta una seconda sessione SSH con `sudo` già
   funzionante, da cui rimuovere il file in caso di problemi.

I permessi `0440` sono obbligatori: `sudo` ignora senza segnalazione i file in `sudoers.d` con
permessi più larghi.

Contenuto:

```
luca ALL=(root) NOPASSWD: /usr/local/sbin/claude-sudo-run
```

### Interruttore

Se `~/.claude/telegram/disabled` esiste, tutti gli hook escono `0` immediatamente. Un `touch` di
quel file disarma il sistema senza modificare la configurazione e senza riavviare nulla.

## Test

Logica pura, in `~/bin/test_claude_telegram.py`, eseguita con `python3 -m unittest`:

- TOTP contro i vettori di test RFC 6238
- tabella comandi verso classificazione distruttivo o non distruttivo, casi al limite inclusi
- regex di rilevamento `sudo`: positivi, e negativi come `echo "sudo"`
- nonce: secondo uso dello stesso callback rifiutato, nonce scaduto rifiutato
- update con `chat_id` estraneo ignorato
- chiave di cache: comandi uguali in `cwd` diversi non collidono
- comando distruttivo mai inserito in cache

Integrazione, con daemon reale:

- daemon fermo: `claude-sudo` nega entro il timeout
- daemon fermo: `claude-tg-notify.sh` esce `0` in meno di 2 s
- turno da 10 s: nessun messaggio; turno da 130 s: messaggio

End-to-end, con il telefono:

- `claude-sudo apt update`: approvazione con un tap, esecuzione
- `claude-sudo rm -rf /tmp/x`: richiesta delle sei cifre
- `claude-sudo systemctl restart claude-rc` approvato su Telegram: nessun prompt nell'app
- seconda invocazione di `claude-sudo apt update` entro il TTL: nessun messaggio, esecuzione
  diretta

## Fuori ambito

- Streaming della conversazione su Telegram; per leggere e lavorare si usa l'app Claude.
- Gate su tool diversi da `Bash`.
- Webhook e qualunque esposizione su internet.
- Whitelist di comandi in sudoers: scartata a favore del wrapper generico.
