import json
import pathlib

DEFAULT_TAIL_BYTES = 262144


def last_assistant_text(path, max_chars=600, tail_bytes=DEFAULT_TAIL_BYTES):
    data = _read_tail(pathlib.Path(path), tail_bytes)
    if data is None:
        return None
    found = None
    for line in data.splitlines():
        text = _assistant_text(line)
        if text:
            found = text
    if found is None:
        return None
    if len(found) <= max_chars:
        return found
    return found[: max_chars - 1].rstrip() + "…"


def _read_tail(path, tail_bytes):
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - tail_bytes))
            raw = handle.read()
    except OSError:
        return None
    return raw.decode("utf-8", errors="replace")


def _assistant_text(line):
    try:
        record = json.loads(line)
    except ValueError:
        return None
    if not isinstance(record, dict) or record.get("type") != "assistant":
        return None
    content = (record.get("message") or {}).get("content")
    if not isinstance(content, list):
        return None
    parts = [
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    joined = "\n".join(part for part in parts if part).strip()
    return joined or None
