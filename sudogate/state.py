"""Store of approved commands, one per token.

Written by the daemon once the owner has tapped Approve, read by the root
wrapper that runs the command. It lives in the daemon's runtime directory,
mode 0700 under the daemon's own account, so the gated user can neither read
a token nor invent a record. That is what ties "the owner approved this" to
"root ran this": before, the record lived in the user's home and anything
running as that user could write one.

The token becomes a file name, so it is validated to rule out path traversal.
Records carry the uid the request came from, and the TOTP code when one was
collected: the code travels from the daemon to root through this directory
and never through a process the gated user controls.
"""
import json
import os
import pathlib
import secrets

SUBDIR = "approved"


def _valid_token(token):
    return bool(token) and all(c.isalnum() or c in "_-" for c in token)

def _dir(home):
    return pathlib.Path(home) / SUBDIR

def _path(home, token):
    return _dir(home) / f"{token}.json"

def create(home, command, cwd, label, now, uid=None, totp=None):
    token = secrets.token_urlsafe(16)
    d = _dir(home)
    d.mkdir(parents=True, exist_ok=True)
    d.chmod(0o700)
    record = {
        "command": command,
        "cwd": cwd,
        "label": label,
        "created_at": now,
        "uid": uid,
        "totp": totp,
        "used": False,
    }
    path = _path(home, token)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record))
    tmp.chmod(0o600)
    os.replace(tmp, path)
    return token

def peek(home, token):
    if not _valid_token(token):
        return None
    try:
        return json.loads(_path(home, token).read_text())
    except (OSError, ValueError):
        return None

def claim(home, token, now, ttl):
    record = peek(home, token)
    if record is None or record.get("used"):
        return None
    if now - record.get("created_at", 0) > ttl:
        return None
    record["used"] = True
    path = _path(home, token)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record))
    tmp.chmod(0o600)
    os.replace(tmp, path)
    return record

def discard(home, token):
    if not _valid_token(token):
        return
    try:
        _path(home, token).unlink(missing_ok=True)
    except OSError:
        pass

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
