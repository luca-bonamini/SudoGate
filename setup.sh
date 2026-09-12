#!/usr/bin/env bash
# setup.sh — installazione guidata della parte utente di sudogate.
# La parte root resta separata e va eseguita a mano: vedi il messaggio finale.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

say "sudogate — installazione guidata"
cat <<'WARN'
Prima di procedere, il compromesso in chiaro:

  sudogate ALZA il privilegio disponibile a Claude, non lo abbassa.
  Oggi la richiesta di password impedisce a Claude di eseguire comandi
  privilegiati. Dopo, Claude puo eseguire qualsiasi comando come root,
  a patto che tu prema Approva sul telefono.

  Per i comandi NON distruttivi, chi puo eseguire codice come il tuo
  utente arriva a root con quel tap. Il secondo fattore TOTP copre solo
  i comandi che corrispondono alla lista dei distruttivi.

Installa solo se il compromesso ti sta bene.
WARN
read -r -p $'\nProseguo? [scrivi si] ' answer
[ "$answer" = "si" ] || { echo "Interrotto."; exit 1; }

say "1/4 — Verifica dei requisiti"
command -v python3 >/dev/null || { echo "python3 mancante" >&2; exit 1; }
python3 - <<'PY'
import sys
if sys.version_info < (3, 11):
    sys.exit(f"serve Python 3.11+, trovato {sys.version.split()[0]}")
print("python3", sys.version.split()[0], "ok")
PY
command -v systemctl >/dev/null || echo "  attenzione: systemctl assente, il daemon andra avviato a mano"
command -v qrencode >/dev/null || echo "  attenzione: qrencode assente, il seed mostrera un URI invece del QR"

say "2/4 — Copia di libreria, eseguibili e unit"
"$repo/install.sh"

say "3/4 — Bot Telegram"
cat <<'BOT'
Su Telegram, con @BotFather:
  /newbot  -> scegli un nome -> copia il token
Poi APRI la chat del bot appena creato e mandagli un messaggio qualsiasi.
Un bot non puo scriverti finche non gli hai scritto tu.

Usa un bot dedicato: getUpdates ammette un solo lettore per bot.
BOT
read -r -p $'\nFatto? Invio per continuare con il token. ' _
"$HOME/bin/sudogate-bootstrap"

say "4/4 — Seed TOTP"
echo "Sto per mostrare un QR: inquadralo con l'app authenticator."
read -r -p "Invio quando sei pronto. " _
"$HOME/bin/sudogate-seed"

say "Parte utente completata. Resta la parte root, che devi eseguire tu."
cat <<ROOT

  Un file malformato in /etc/sudoers.d/ puo rompere l'escalation su tutta
  la macchina. Apri una SECONDA sessione SSH, verifica che l'elevazione
  funzioni li, e LASCIALA APERTA.

Poi, con privilegi di root:

  $repo/install-root.sh

Infine:

  shred -u /tmp/sudogate-seed
  systemctl --user enable --now sudogate

ROOT
