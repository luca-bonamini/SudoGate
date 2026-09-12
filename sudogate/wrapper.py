"""Logic of the root wrapper (/usr/local/sbin/sudogate-run).

It trusts neither the destructive flag in the state file nor the pattern list
on the user side: it re-classifies the command with the root-owned patterns
and, when a second factor is required, checks the TOTP against the root-owned
seed. That is what keeps the second factor standing against code running as
the user.

The "always require TOTP" policy is root-owned too, for the same reason: a
flag the user could clear would not be a policy.
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


def load_totp_always(path):
    """True when every command needs a TOTP code, not only destructive ones.

    The policy is the presence of a root-owned file. It lives next to the seed
    so that the unprivileged user can read it — the shim needs to know whether
    to collect a code — but cannot remove it.
    """
    return pathlib.Path(path).exists()


def requires_totp(command, patterns, always=False):
    return bool(always) or gate.is_destructive(command, patterns)


def authorize(command, patterns, seed, totp_code, now, always=False):
    if requires_totp(command, patterns, always):
        if not seed:
            return False, "TOTP seed missing, command denied"
        if not totp.verify(seed, totp_code or "", at_time=now):
            return False, "TOTP code invalid or expired"
    return True, "authorized"
