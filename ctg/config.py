import json
import os
import pathlib

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


class ConfigError(Exception):
    """Configurazione assente, illeggibile o con permessi sbagliati."""


def home():
    override = os.environ.get("CTG_HOME")
    if override:
        return pathlib.Path(override)
    return pathlib.Path.home() / ".claude" / "telegram"


def config_path():
    return home() / "config.json"


def load(path=None):
    path = pathlib.Path(path) if path is not None else config_path()
    try:
        mode = path.stat().st_mode & 0o777
    except OSError as exc:
        raise ConfigError(f"configurazione non leggibile: {path}") from exc
    if mode & 0o077:
        raise ConfigError(f"permessi {mode:04o} troppo larghi su {path}, attesi 0600")
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ConfigError(f"configurazione illeggibile: {path}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"la configurazione in {path} non è un oggetto JSON")
    if not raw.get("bot_token"):
        raise ConfigError(f"bot_token mancante in {path}")
    cfg = dict(DEFAULTS)
    cfg.update(raw)
    return cfg
