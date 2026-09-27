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

SEED = pathlib.Path("/etc/sudogate/seed")
PATTERNS = pathlib.Path("/etc/sudogate/destructive.patterns")
TOTP_ALWAYS = pathlib.Path("/etc/sudogate/totp_always")
AUDIT = pathlib.Path("/var/log/sudogate/audit.log")

_OVERRIDES = {
    "seed": ("SUDOGATE_SEED", SEED),
    "patterns": ("SUDOGATE_PATTERNS", PATTERNS),
    "totp_always": ("SUDOGATE_TOTP_ALWAYS", TOTP_ALWAYS),
    "audit": ("SUDOGATE_AUDIT", AUDIT),
}


def resolve_paths(euid, environ, user_home):
    """Where the root wrapper reads its seed, patterns, policy and log.

    As root these are constants. Honouring SUDOGATE_* there would hand the
    second factor to whoever can set the environment of the sudo call: point
    SUDOGATE_SEED at a file you wrote and every code you type verifies.

    Below root the overrides stand. A process with no privilege to escalate
    gains nothing from them, and the test suite runs that way.

    The state file is the user's by design - the shim writes it - so only its
    location is pinned, never its owner.
    """
    root = euid == 0
    paths = {
        key: default if root else pathlib.Path(environ.get(var) or default)
        for key, (var, default) in _OVERRIDES.items()
    }
    state_home = user_home / ".config" / "sudogate"
    if not root and environ.get("SUDOGATE_STATE_HOME"):
        state_home = pathlib.Path(environ["SUDOGATE_STATE_HOME"])
    paths["state_home"] = state_home
    return paths


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
