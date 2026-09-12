"""Logic of the root wrapper (/usr/local/sbin/sudogate-run).

It trusts neither the destructive flag in the state file nor the pattern list
on the user side: it re-classifies the command with the root-owned patterns
and, if destructive, requires a valid TOTP checked against the root-owned
seed. That is what keeps the second factor standing against code running as
the user.
"""
import pathlib

from sudogate import config, gate, totp


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
            return False, "TOTP seed missing, destructive command denied"
        if not totp.verify(seed, totp_code or "", at_time=now):
            return False, "TOTP code invalid or expired"
    return True, "authorized"
