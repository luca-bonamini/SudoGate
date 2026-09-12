"""Classificazione dei comandi per il gate sudo.

contains_sudo riconosce sudo in posizione di comando, escludendo lo shim
sudogate e sudo usato come argomento. is_destructive decide se il
comando richiede il secondo fattore TOTP.
"""
import re

# sudo a inizio riga o dopo un separatore di shell, ma non sudogate
# (preceduto da '-') ne sudo come argomento (preceduto da spazio o quote).
_SUDO_RE = re.compile(r"(^|[;&|(\n]\s*)sudo\b")

# Corpo di un heredoc: <<EOF ... EOF, <<'EOF' ... EOF, <<-"EOF" ... EOF.
_HEREDOC_RE = re.compile(
    r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1.*?^\s*\2\s*$",
    re.DOTALL | re.MULTILINE,
)


def strip_heredocs(command):
    """Rimuove i corpi degli heredoc da un comando di shell.

    Il payload dell'hook contiene l'intero comando, heredoc inclusi. Senza
    questo, scrivere un file che *parla* di sudo verrebbe scambiato per un
    tentativo di eseguirlo. Il delimitatore di apertura resta, cosi la
    struttura della riga che apre l'heredoc non va persa.
    """
    return _HEREDOC_RE.sub("<<STRIPPED", command or "")


def contains_sudo(command):
    return _SUDO_RE.search(strip_heredocs(command)) is not None


def is_destructive(command, patterns):
    command = strip_heredocs(command)
    for pattern in patterns:
        if re.search(pattern, command):
            return True
    return False
