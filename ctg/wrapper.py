"""Logica del wrapper root (/usr/local/sbin/claude-sudo-run).

Non si fida ne del flag destructive dello state file ne dei pattern lato
luca: ri-classifica il comando con i pattern root-only e, se distruttivo,
pretende un TOTP valido verificato contro il seed root-only. Cosi anche
codice che gira come luca non aggira il secondo fattore sui distruttivi.
"""
import pathlib

from ctg import config, gate, totp


def load_patterns(path):
    try:
        lines = pathlib.Path(path).read_text().splitlines()
    except OSError:
        return list(config.DEFAULTS["destructive_patterns"])
    patterns = [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]
    return patterns or list(config.DEFAULTS["destructive_patterns"])


def load_seed(path):
    try:
        seed = pathlib.Path(path).read_text().strip()
    except OSError:
        return None
    return seed or None


def authorize(command, patterns, seed, totp_code, now):
    if gate.is_destructive(command, patterns):
        if not seed:
            return False, "seed TOTP assente, comando distruttivo negato"
        if not totp.verify(seed, totp_code or "", at_time=now):
            return False, "TOTP non valido o scaduto"
    return True, "autorizzato"
