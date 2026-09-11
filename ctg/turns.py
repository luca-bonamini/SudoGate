import json
import os
import pathlib


def should_notify_stop(elapsed, threshold, from_telegram):
    if from_telegram:
        return True
    return elapsed is not None and elapsed >= threshold


class TurnClock:
    """Istante dell'ultimo prompt utente, per sessione, su file."""

    def __init__(self, path):
        self._path = pathlib.Path(path)

    def mark_prompt(self, session_id, now):
        data = self._read()
        data[session_id] = now
        self._write(data)

    def elapsed(self, session_id, now):
        started = self._read().get(session_id)
        if started is None:
            return None
        return now - started

    def clear(self, session_id):
        data = self._read()
        if data.pop(session_id, None) is not None:
            self._write(data)

    def _read(self):
        try:
            data = json.loads(self._path.read_text())
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, data):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        os.replace(tmp, self._path)
