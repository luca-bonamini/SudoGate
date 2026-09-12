"""Cache of approvals, so repeating the same command in the same directory
does not ask for a button every time.

Key: sha256(cwd + NUL + command). Exact match, never a prefix. Destructive
commands must never be cached: it is the caller's job not to call remember
for those.
"""
import hashlib
import json
import os
import pathlib


def _key(cwd, command):
    raw = f"{cwd}\x00{command}".encode()
    return hashlib.sha256(raw).hexdigest()


def _read(path):
    try:
        data = json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(path, data):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.chmod(0o600)
    os.replace(tmp, path)


def is_approved(path, cwd, command, now):
    entry = _read(path).get(_key(cwd, command))
    return bool(entry) and entry.get("expires_at", 0) > now


def remember(path, cwd, command, now, ttl):
    data = {k: v for k, v in _read(path).items() if v.get("expires_at", 0) > now}
    data[_key(cwd, command)] = {"expires_at": now + ttl}
    _write(path, data)
