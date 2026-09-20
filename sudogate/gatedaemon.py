"""Gate daemon: the approval conversation on Telegram.

It runs under its own system account, not the account being gated, and it is
where every decision is made. The shim sends a command; the daemon classifies
it against the root-owned pattern list, asks Telegram, collects the TOTP code
when one is required, and — only on approval — writes the command to the
approved-record directory and hands back the token that names it.

The shim is not trusted with any of that. It cannot say a command is harmless,
it cannot pre-fill the approval cache, and it never sees the TOTP code: the
code goes from Telegram into the record that root reads. What the owner sees
on the phone and what root runs are the same record.

The daemon still does not verify the code. That happens root-side against the
seed at 0400 root, which this account cannot read either.
"""
import secrets
import threading
import time

from sudogate import cache, gate, state


class _Pending:
    def __init__(self, event, destructive):
        self.event = event
        self.destructive = destructive
        self.verdict = None
        self.totp = None
        self.reason = ""
        self.awaiting_totp = False


class GateDaemon:
    def __init__(self, cfg, client, home, patterns=None, totp_always=False,
                 cache_path=None):
        self._cfg = cfg
        self._client = client
        self._home = home
        self._chat_id = cfg["chat_id"]
        # Root-owned policy, read once at start. The user config can add
        # friction but never remove it, so a pattern list passed here wins.
        self._patterns = list(patterns if patterns is not None
                              else cfg.get("destructive_patterns", []))
        self._totp_always = bool(totp_always) or bool(cfg.get("totp_always"))
        self._cache_path = cache_path
        self._pending = {}
        self._lock = threading.Lock()

    def classify(self, command):
        """True when the command needs the TOTP second factor.

        Decided here, against the root-owned list, because the shim runs as
        the account the gate exists to constrain.
        """
        return self._totp_always or gate.is_destructive(command, self._patterns)

    def on_shim_request(self, payload, peer):
        command = payload.get("command") or ""
        if not command:
            return {"verdict": "deny", "token": None, "reason": "empty command"}
        cwd = payload.get("cwd") or "/"
        label = payload.get("label") or "?"
        now = time.time()
        destructive = self.classify(command)

        if not destructive and self._cached(cwd, command, now):
            return self._approve(command, cwd, label, peer, None, now,
                                 "approved from cache")

        nonce = secrets.token_urlsafe(8)
        text = self._compose(command, label, destructive)
        buttons = [[("Approva", f"a:{nonce}"), ("Nega", f"n:{nonce}")]]
        try:
            self._client.send_message(self._chat_id, text, buttons)
        except Exception as exc:  # noqa: BLE001
            return {"verdict": "deny", "token": None, "reason": f"send failed: {exc}"}
        event = threading.Event()
        pending = _Pending(event, destructive)
        with self._lock:
            self._pending[nonce] = pending
        got = event.wait(self._cfg.get("approval_ttl_seconds", 120))
        with self._lock:
            self._pending.pop(nonce, None)
        if not got:
            return {"verdict": "deny", "token": None, "reason": "timed out with no answer"}
        if pending.verdict != "approve":
            return {"verdict": "deny", "token": None, "reason": pending.reason}

        if not destructive:
            self._remember(cwd, command, time.time())
        return self._approve(command, cwd, label, peer, pending.totp, time.time(),
                             pending.reason)

    def _approve(self, command, cwd, label, peer, totp, now, reason):
        token = state.create(self._home, command, cwd, label, now,
                             uid=getattr(peer, "uid", None), totp=totp)
        return {"verdict": "approve", "token": token, "reason": reason}

    def _cached(self, cwd, command, now):
        if not self._cache_path:
            return False
        return cache.is_approved(self._cache_path, cwd, command, now)

    def _remember(self, cwd, command, now):
        if not self._cache_path:
            return
        cache.remember(self._cache_path, cwd, command, now,
                       self._cfg.get("cache_ttl_seconds", 28800))

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

    def _compose(self, command, label, destructive):
        head = f"[{label}] privileged command"
        if destructive:
            head += " — destructive, a code will be required"
        return f"{head}\n\n{command}"

    def _safe_send(self, text):
        try:
            self._client.send_message(self._chat_id, text)
        except Exception:  # noqa: BLE001
            pass
