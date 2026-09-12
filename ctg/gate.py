"""Classificazione dei comandi per il gate sudo.

contains_sudo riconosce sudo in posizione di comando, escludendo lo shim
claude-sudo e sudo usato come argomento. is_destructive decide se il
comando richiede il secondo fattore TOTP.
"""
import re

# sudo a inizio riga o dopo un separatore di shell, ma non claude-sudo
# (preceduto da '-') ne sudo come argomento (preceduto da spazio o quote).
_SUDO_RE = re.compile(r"(^|[;&|(]\s*)sudo\b")


def contains_sudo(command):
    return _SUDO_RE.search(command or "") is not None


def is_destructive(command, patterns):
    command = command or ""
    for pattern in patterns:
        if re.search(pattern, command):
            return True
    return False
