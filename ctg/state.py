"""Store dei comandi sudo in attesa di approvazione, uno per nonce.

Scritto dallo shim (che gira come luca), letto dal daemon per mostrare
il comando nel messaggio, e dal wrapper (root) che lo esegue. Il nonce e
un nome di file: viene validato per escludere path traversal.
"""
import json
import os
import pathlib
import secrets

_NONCE_RE = None


def _valid_nonce(nonce):
    return bool(nonce) and all(c.isalnum() or c in "_-" for c in nonce)


def _dir(home):
    return pathlib.Path(home) / "state"


def _path(home, nonce):
    return _dir(home) / f"{nonce}.json"


def create(home, command, cwd, label, now):
    nonce = secrets.token_urlsafe(16)
    d = _dir(home)
    d.mkdir(parents=True, exist_ok=True)
    record = {
        "command": command,
        "cwd": cwd,
        "label": label,
        "created_at": now,
        "used": False,
    }
    path = _path(home, nonce)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record))
    tmp.chmod(0o600)
    os.replace(tmp, path)
    return nonce


def peek(home, nonce):
    if not _valid_nonce(nonce):
        return None
    try:
        return json.loads(_path(home, nonce).read_text())
    except (OSError, ValueError):
        return None


def claim(home, nonce, now, ttl):
    record = peek(home, nonce)
    if record is None or record.get("used"):
        return None
    if now - record.get("created_at", 0) > ttl:
        return None
    record["used"] = True
    path = _path(home, nonce)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record))
    tmp.chmod(0o600)
    os.replace(tmp, path)
    return record


def purge(home, now, ttl):
    d = _dir(home)
    if not d.is_dir():
        return
    for path in d.glob("*.json"):
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError):
            path.unlink(missing_ok=True)
            continue
        if now - record.get("created_at", 0) > ttl:
            path.unlink(missing_ok=True)
