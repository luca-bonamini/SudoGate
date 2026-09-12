"""Gate daemon: the approval conversation on Telegram.

Receives a request for a nonce from the shim over IPC, sends an Approve/Deny
message on the dedicated bot, and for destructive commands collects the TOTP
reply. It returns the verdict and, when collected, the code. It never
verifies the code: that happens root-side against the root-owned seed. Here
the code is only carried.
"""
import threading


class _Pending:
    def __init__(self, event, destructive):
        self.event = event
        self.destructive = destructive
        self.verdict = None
        self.totp = None
        self.reason = ""
        self.awaiting_totp = False


class GateDaemon:
    def __init__(self, cfg, client, home):
        self._cfg = cfg
        self._client = client
        self._home = home
        self._chat_id = cfg["chat_id"]
        self._pending = {}
        self._lock = threading.Lock()

    def on_shim_request(self, payload):
        nonce = payload["nonce"]
        destructive = bool(payload.get("destructive"))
        text = self._compose(payload)
        buttons = [[("Approva", f"a:{nonce}"), ("Nega", f"n:{nonce}")]]
        try:
            self._client.send_message(self._chat_id, text, buttons)
        except Exception as exc:  # noqa: BLE001
            return {"verdict": "deny", "totp": None, "reason": f"send failed: {exc}"}
        event = threading.Event()
        pending = _Pending(event, destructive)
        with self._lock:
            self._pending[nonce] = pending
        got = event.wait(self._cfg.get("approval_ttl_seconds", 120))
        with self._lock:
            self._pending.pop(nonce, None)
        if not got:
            return {"verdict": "deny", "totp": None, "reason": "timed out with no answer"}
        return {"verdict": pending.verdict, "totp": pending.totp, "reason": pending.reason}

    def on_update(self, update):
        callback = update.get("callback_query")
        if callback is not None:
            self._on_callback(callback)
            return
        message = update.get("message")
        if message is not None:
            self._on_message(message)

    def _on_callback(self, callback):
        chat_id = ((callback.get("message") or {}).get("chat") or {}).get("id")
        if chat_id != self._chat_id:
            return
        data = callback.get("data") or ""
        action, _, nonce = data.partition(":")
        with self._lock:
            pending = self._pending.get(nonce)
            if pending is None:
                return
            if action == "n":
                pending.verdict = "deny"
                pending.reason = "denied by the user"
                pending.event.set()
                return
            if action != "a":
                return
            if pending.destructive and pending.totp is None and not pending.awaiting_totp:
                pending.awaiting_totp = True
                prompt = True
            else:
                pending.verdict = "approve"
                pending.reason = "approved"
                pending.event.set()
                prompt = False
        if prompt:
            self._safe_send("Approved. Now send the 6-digit code to confirm.")

    def _on_message(self, message):
        chat_id = (message.get("chat") or {}).get("id")
        if chat_id != self._chat_id:
            return
        digits = "".join(c for c in (message.get("text") or "") if c.isdigit())
        if len(digits) != 6:
            return
        with self._lock:
            target = next(
                (p for p in self._pending.values() if p.awaiting_totp and p.totp is None),
                None,
            )
            if target is None:
                return
            target.totp = digits
            target.verdict = "approve"
            target.reason = "approved with TOTP"
            target.event.set()

    def _compose(self, payload):
        head = f"[{payload.get('label', '?')}] privileged command"
        if payload.get("destructive"):
            head += " — destructive, a code will be required"
        return f"{head}\n\n{payload.get('command', '')}"

    def _safe_send(self, text):
        try:
            self._client.send_message(self._chat_id, text)
        except Exception:  # noqa: BLE001
            pass
