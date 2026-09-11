import json
import os
import pathlib


def first_chat_id(updates):
    for update in updates:
        chat = ((update.get("message") or {}).get("chat")) or {}
        if "id" in chat:
            return chat["id"]
    return None


def write_config(path, token, chat_id):
    path = pathlib.Path(path)
    try:
        existing = json.loads(path.read_text())
    except (OSError, ValueError):
        existing = {}
    if not isinstance(existing, dict):
        existing = {}
    existing["bot_token"] = token
    existing["chat_id"] = chat_id
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(existing, indent=2))
    tmp.chmod(0o600)
    os.replace(tmp, path)
