# Migrazione dell'installazione di home-server ai nomi sudogate

Al 12 settembre 2026 `home-server` gira ancora sulla prima installazione, quella con i nomi
precedenti. Funziona: non è stata toccata durante il rilascio pubblico.

| componente | ora | dopo |
|---|---|---|
| shim | `~/bin/claude-sudo` | `~/bin/sudogate` |
| wrapper root | `/usr/local/sbin/claude-sudo-run` | `/usr/local/sbin/sudogate-run` |
| daemon | unit `ctg-gate` | unit `sudogate` |
| hook | `~/bin/claude-tg-gate` | quello del plugin |
| libreria | `~/.local/lib/claude-telegram/ctg` | `~/.local/lib/sudogate/sudogate` |
| config | `~/.claude/telegram/config.json` | `~/.config/sudogate/config.json` |
| root | `/etc/claude-gate/`, `/etc/sudoers.d/claude-gate` | `/etc/sudogate/`, `/etc/sudoers.d/sudogate` |

Il seed TOTP **non cambia**: `install-root.sh` riusa `/tmp/sudogate-seed`, quindi serve
rigenerarlo e riscansionare il QR, oppure copiare il seed attuale. Rigenerare è più pulito.

## Ordine

Serve una seconda sessione SSH con elevazione funzionante, aperta per tutta la procedura.

**1. Parte utente e configurazione.**

```
cd ~/Project/personal/sudogate
./install.sh
mkdir -p ~/.config/sudogate && chmod 700 ~/.config/sudogate
cp ~/.claude/telegram/config.json ~/.config/sudogate/config.json
chmod 600 ~/.config/sudogate/config.json
```

**2. Nuovo seed.**

```
~/bin/sudogate-seed
```

Scansiona il QR: comparirà come `sudogate:home-server`. Elimina poi la vecchia voce
`claude-gate:home-server` dall'authenticator, ma solo dopo il punto 5.

**3. Parte root.** Con privilegi di root, da `~/Project/personal/sudogate`:

```
./install-root.sh
```

**4. Rimozione della vecchia installazione root.** Sempre con privilegi di root:

```
rm -f /etc/sudoers.d/claude-gate /usr/local/sbin/claude-sudo-run
rm -rf /etc/claude-gate
visudo -c
```

`visudo -c` deve dire `parsed OK`. Il vecchio log in `/var/log/claude-gate/` si può tenere come
archivio o spostare in `/var/log/sudogate/`.

**5. Daemon.**

```
systemctl --user disable --now ctg-gate
systemctl --user enable --now sudogate
systemctl --user is-active sudogate
```

**6. Hook.** In `~/.claude/settings.json`, togliere la voce `PreToolUse` che punta a
`$HOME/bin/claude-tg-gate` e cambiare la allowlist da `Bash(claude-sudo:*)` a
`Bash(sudogate:*)`. Poi installare il plugin, che porta il proprio hook:

```
/plugin install sudogate@sudogate
```

**7. Pulizia.**

```
shred -u /tmp/sudogate-seed
rm -rf ~/.local/lib/claude-telegram ~/bin/claude-sudo ~/bin/claude-tg-gate ~/bin/ctg-*
rm -rf ~/.claude/telegram
rm -f ~/.config/systemd/user/ctg-gate.service && systemctl --user daemon-reload
```

## Verifica finale

| controllo | atteso |
|---|---|
| `systemctl --user is-active sudogate` | `active` |
| `visudo -c` come root | `parsed OK` |
| lettura di `/etc/sudogate/seed` come `luca` | `Permission denied` |
| `sudogate id -un` | `root`, dopo un tap |
| distruttivo con codice sbagliato | negato e non eseguito |

## Se qualcosa si rompe

La via di rientro è la seconda sessione SSH. Il caso peggiore è la riga sudoers: se sparisce
l'elevazione, da quella sessione rimuovi i file in `/etc/sudoers.d/` aggiunti al punto 3.

Finché il punto 4 non è eseguito, la vecchia installazione root resta in piedi e funzionante:
si può interrompere la migrazione dopo il punto 3 senza restare senza gate.
