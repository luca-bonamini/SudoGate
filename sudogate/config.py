import json
import os
import pathlib
import pwd

DEFAULTS = {
    "chat_id": None,
    "stop_threshold_seconds": 120,
    "transcript_tail_chars": 600,
    "approval_ttl_seconds": 120,
    "cache_ttl_seconds": 28800,
    "totp_always": False,
    "destructive_patterns": [
        r"\brm\s+(-\w+\s+)*-\w*(r\w*f|f\w*r)",
        r"\bdd\b",
        r"\bmkfs\b",
        r"\b(fdisk|parted)\b",
        r"\b(shutdown|reboot|poweroff|halt)\b",
        r"\b(passwd|usermod|useradd|userdel)\b",
        r"\b(visudo|sudoers)\b",
        r"/etc/netplan",
        r"\b(chown|chmod)\b.*\s-\w*R",
        r"\b(iptables|ufw|nft)\b",
        r"\bsystemctl\s+(disable|mask)\b",
        r"\bapt(-get)?\s+(remove|purge|autoremove)\b",
        r"\|\s*(ba)?sh\b",
        r">\s*/dev/(sd|nvme|vd)",
        r"\btailscale\s+down\b",
    ],
}


# The daemon's own account and the directories it owns. None of these are
# writable by the account the gate exists to constrain: that is the point.
DAEMON_USER = "sudogate"
SYSTEM_HOME = pathlib.Path("/etc/sudogate")
RUNTIME_DIR = pathlib.Path("/run/sudogate")
CACHE_DIR = pathlib.Path("/var/lib/sudogate")
SOCKET_NAME = "gate.sock"


class ConfigError(Exception):
    """Config file missing, unreadable, or with permissions that are too open."""


def home():
    override = os.environ.get("SUDOGATE_HOME")
    if override:
        return pathlib.Path(override)
    return pathlib.Path.home() / ".config" / "sudogate"


def config_path():
    return home() / "config.json"


def system_config_path():
    """Where the daemon reads its configuration.

    It holds the bot token, so it is owned by the daemon account at 0400 and
    is not readable by the gated user — who, before, kept the same token in
    their own home and could therefore impersonate the daemon outright.
    """
    override = os.environ.get("SUDOGATE_SYSTEM_CONFIG")
    return pathlib.Path(override) if override else SYSTEM_HOME / "config.json"


def runtime_dir():
    override = os.environ.get("SUDOGATE_RUNTIME_DIR")
    return pathlib.Path(override) if override else RUNTIME_DIR


def socket_path():
    return runtime_dir() / SOCKET_NAME


def gated_uid(cfg):
    """uid of the single account allowed to ask the gate for anything."""
    if cfg.get("gated_uid") is not None:
        return int(cfg["gated_uid"])
    user = cfg.get("gated_user")
    if not user:
        raise ConfigError("neither gated_uid nor gated_user is set")
    try:
        return pwd.getpwnam(user).pw_uid
    except KeyError as exc:
        raise ConfigError(f"unknown gated_user: {user}") from exc


def load(path=None):
    path = pathlib.Path(path) if path is not None else config_path()
    try:
        mode = path.stat().st_mode & 0o777
    except OSError as exc:
        raise ConfigError(f"config not readable: {path}") from exc
    if mode & 0o077:
        raise ConfigError(f"permissions {mode:04o} too open on {path}, expected 0600")
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ConfigError(f"config unreadable: {path}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"config in {path} is not a JSON object")
    if not raw.get("bot_token"):
        raise ConfigError(f"bot_token missing in {path}")
    cfg = dict(DEFAULTS)
    cfg.update(raw)
    return cfg
