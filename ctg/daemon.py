import signal
import threading
import time

from ctg import config, ipc, messages, sessions, telegram, transcript, turns

POLL_TIMEOUT_SECONDS = 30
RETRY_WAIT_SECONDS = 5


class Daemon:
    def __init__(self, cfg, client, clock, sessions_reader=None, transcript_reader=None):
        self._cfg = cfg
        self._client = client
        self._clock = clock
        self._sessions_reader = sessions_reader or sessions.tmux_sessions
        self._transcript_reader = transcript_reader or (
            lambda path, max_chars: transcript.last_assistant_text(path, max_chars=max_chars)
        )
        self.started_at = time.time()

    def handle_hook(self, payload, now=None):
        now = time.time() if now is None else now
        event = payload.get("hook_event_name")
        if event == "UserPromptSubmit":
            session_id = payload.get("session_id")
            if session_id:
                self._clock.mark_prompt(session_id, now)
            return {"sent": False, "reason": "t0 registrato"}
        if event == "Notification":
            return self._send(
                messages.notification(self._label(payload), payload.get("message", ""))
            )
        if event == "Stop":
            return self._handle_stop(payload, now)
        return {"sent": False, "reason": f"evento ignorato: {event}"}

    def handle_update(self, update):
        message = update.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        if chat_id is None or chat_id != self._cfg.get("chat_id"):
            return
        text = (message.get("text") or "").strip()
        if not text:
            return
        self._send(self._reply_to(text))

    def _reply_to(self, text):
        if text.startswith("/stato"):
            uptime = int(time.time() - self.started_at)
            live = ", ".join(sorted(self._sessions_reader())) or "nessuna"
            return f"daemon attivo da {uptime}s\nsessioni tmux: {live}"
        return "comando non riconosciuto. Disponibile: /stato"

    def _handle_stop(self, payload, now):
        session_id = payload.get("session_id")
        elapsed = self._clock.elapsed(session_id, now) if session_id else None
        if session_id:
            self._clock.clear(session_id)
        if not turns.should_notify_stop(
            elapsed, self._cfg["stop_threshold_seconds"], from_telegram=False
        ):
            return {"sent": False, "reason": "turno sotto soglia"}
        summary = None
        path = payload.get("transcript_path")
        if path:
            summary = self._transcript_reader(path, self._cfg["transcript_tail_chars"])
        return self._send(messages.stop(self._label(payload), summary))

    def _label(self, payload):
        return sessions.label_for_cwd(payload.get("cwd", ""), self._sessions_reader())

    def _send(self, text):
        chat_id = self._cfg.get("chat_id")
        if chat_id is None:
            return {"sent": False, "reason": "chat_id non configurato"}
        try:
            self._client.send_message(chat_id, text)
        except telegram.TelegramError as exc:
            return {"sent": False, "reason": str(exc)}
        return {"sent": True, "reason": "inviato"}


def main(argv=None):
    cfg = config.load()
    client = telegram.Client(cfg["bot_token"])
    clock = turns.TurnClock(config.home() / "turns.json")
    instance = Daemon(cfg, client, clock)
    stop_event = threading.Event()

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop_event.set())

    server = threading.Thread(
        target=ipc.serve,
        args=(config.home() / "sock", instance.handle_hook, stop_event),
        daemon=True,
    )
    server.start()

    offset = 0
    while not stop_event.is_set():
        try:
            updates = client.get_updates(offset, timeout=POLL_TIMEOUT_SECONDS)
        except telegram.TelegramError:
            stop_event.wait(RETRY_WAIT_SECONDS)
            continue
        for update in updates:
            offset = update["update_id"] + 1
            instance.handle_update(update)
    server.join(5)
    return 0
