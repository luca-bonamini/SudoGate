import pathlib
import tempfile
import threading
import time
import unittest

from sudogate import cache, gatedaemon, state


class FakeClient:
    def __init__(self):
        self.sent = []
        self._id = 0

    def send_message(self, chat_id, text, buttons=None):
        self._id += 1
        self.sent.append((chat_id, text, buttons))
        return {"message_id": self._id}


class Peer:
    def __init__(self, uid=1000):
        self.pid, self.uid, self.gid = 4242, uid, uid


CFG = {"bot_token": "T", "chat_id": 42, "approval_ttl_seconds": 5}
PATTERNS = [r"\brm\s+(-\w+\s+)*-\w*(r\w*f|f\w*r)", r"\bmkfs\b"]


class GateDaemonCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = pathlib.Path(self._tmp.name)
        self.cache_path = self.home / "cache.json"
        self.addCleanup(self._tmp.cleanup)
        self.client = FakeClient()
        self.d = self.make_daemon()

    def make_daemon(self, cfg=None, **kwargs):
        kwargs.setdefault("patterns", PATTERNS)
        kwargs.setdefault("cache_path", self.cache_path)
        return gatedaemon.GateDaemon(cfg or CFG, self.client, self.home, **kwargs)

    def payload(self, command="apt update", **extra):
        return {"command": command, "cwd": "/tmp", "label": "personal", **extra}

    def ask(self, daemon, payload):
        result = {}
        t = threading.Thread(target=lambda: result.update(daemon.on_shim_request(payload, Peer())))
        t.start()
        return result, t

    def wait_pending(self, daemon=None):
        daemon = daemon or self.d
        for _ in range(100):
            with daemon._lock:
                if daemon._pending:
                    return next(iter(daemon._pending))
            time.sleep(0.02)
        self.fail("pending entry never registered")

    def tap(self, nonce, action="a", chat_id=42, daemon=None):
        (daemon or self.d).on_update(
            {"callback_query": {"message": {"chat": {"id": chat_id}}, "data": f"{action}:{nonce}"}}
        )


class TestClassification(GateDaemonCase):
    def test_the_shim_does_not_decide_what_is_destructive(self):
        """A shim claiming a command is harmless is ignored: it runs as the
        account the gate exists to constrain."""
        self.assertTrue(self.d.classify("rm -rf /tmp/x"))
        self.assertFalse(self.d.classify("apt update"))

    def test_a_payload_claiming_not_destructive_still_asks_for_a_code(self):
        result, t = self.ask(self.d, self.payload("rm -rf /tmp/x", destructive=False))
        nonce = self.wait_pending()
        self.tap(nonce)  # first tap only asks for the digits
        with self.d._lock:
            self.assertTrue(self.d._pending[nonce].awaiting_totp)
        self.d.on_update({"message": {"chat": {"id": 42}, "text": "123456"}})
        t.join(3)
        self.assertEqual(result["verdict"], "approve")

    def test_totp_always_makes_every_command_destructive(self):
        d = self.make_daemon(totp_always=True)
        self.assertTrue(d.classify("apt update"))

    def test_the_user_config_can_add_friction_not_remove_it(self):
        d = self.make_daemon(cfg=dict(CFG, totp_always=True), totp_always=False)
        self.assertTrue(d.classify("apt update"))


class TestNonDestructive(GateDaemonCase):
    def test_approve_with_button_mints_a_token(self):
        result, t = self.ask(self.d, self.payload())
        nonce = self.wait_pending()
        self.tap(nonce)
        t.join(3)
        self.assertEqual(result["verdict"], "approve")
        record = state.peek(self.home, result["token"])
        self.assertEqual(record["command"], "apt update")
        self.assertEqual(record["uid"], 1000)
        self.assertIsNone(record["totp"])

    def test_deny_with_button_mints_nothing(self):
        result, t = self.ask(self.d, self.payload())
        nonce = self.wait_pending()
        self.tap(nonce, action="n")
        t.join(3)
        self.assertEqual(result["verdict"], "deny")
        self.assertIsNone(result["token"])
        self.assertEqual(list((self.home / state.SUBDIR).glob("*.json")), [])

    def test_empty_command_is_refused_without_asking(self):
        reply = self.d.on_shim_request(self.payload(command=""), Peer())
        self.assertEqual(reply["verdict"], "deny")
        self.assertEqual(self.client.sent, [])


class TestDestructive(GateDaemonCase):
    def test_approve_then_asks_and_carries_the_totp_in_the_record(self):
        result, t = self.ask(self.d, self.payload("rm -rf /tmp/x"))
        nonce = self.wait_pending()
        self.tap(nonce)
        with self.d._lock:
            self.assertTrue(self.d._pending[nonce].awaiting_totp)
        self.d.on_update({"message": {"chat": {"id": 42}, "text": "123456"}})
        t.join(3)
        self.assertEqual(result["verdict"], "approve")
        self.assertEqual(state.peek(self.home, result["token"])["totp"], "123456")

    def test_the_code_is_not_returned_to_the_shim(self):
        """It travels to root through the record, not through the caller."""
        result, t = self.ask(self.d, self.payload("rm -rf /tmp/x"))
        nonce = self.wait_pending()
        self.tap(nonce)
        self.d.on_update({"message": {"chat": {"id": 42}, "text": "123456"}})
        t.join(3)
        self.assertNotIn("totp", result)

    def test_a_destructive_command_is_never_cached(self):
        result, t = self.ask(self.d, self.payload("rm -rf /tmp/x"))
        nonce = self.wait_pending()
        self.tap(nonce)
        self.d.on_update({"message": {"chat": {"id": 42}, "text": "123456"}})
        t.join(3)
        self.assertFalse(cache.is_approved(self.cache_path, "/tmp", "rm -rf /tmp/x", time.time()))


class TestCache(GateDaemonCase):
    def test_an_approved_command_is_remembered(self):
        result, t = self.ask(self.d, self.payload())
        nonce = self.wait_pending()
        self.tap(nonce)
        t.join(3)
        self.assertTrue(cache.is_approved(self.cache_path, "/tmp", "apt update", time.time()))

    def test_a_remembered_command_skips_the_button(self):
        cache.remember(self.cache_path, "/tmp", "apt update", time.time(), ttl=60)
        reply = self.d.on_shim_request(self.payload(), Peer())
        self.assertEqual(reply["verdict"], "approve")
        self.assertEqual(self.client.sent, [])
        self.assertEqual(state.peek(self.home, reply["token"])["command"], "apt update")

    def test_the_cache_lives_where_the_gated_user_cannot_write_it(self):
        """Not a property of this module, but of where the daemon puts it:
        pre-filling the cache would otherwise skip the button outright."""
        from sudogate import config
        self.assertEqual(config.CACHE_DIR, pathlib.Path("/var/lib/sudogate"))


class TestSecurity(GateDaemonCase):
    def test_discards_callback_from_other_chat(self):
        result, t = self.ask(self.d, self.payload())
        nonce = self.wait_pending()
        self.tap(nonce, chat_id=999)
        time.sleep(0.3)
        with self.d._lock:
            self.assertIn(nonce, self.d._pending)  # unresolved
        self.tap(nonce, action="n")
        t.join(3)
        self.assertEqual(result["verdict"], "deny")

    def test_discards_a_code_from_another_chat(self):
        result, t = self.ask(self.d, self.payload("rm -rf /tmp/x"))
        nonce = self.wait_pending()
        self.tap(nonce)
        self.d.on_update({"message": {"chat": {"id": 999}, "text": "123456"}})
        time.sleep(0.3)
        with self.d._lock:
            self.assertIsNone(self.d._pending[nonce].totp)
        self.d.on_update({"message": {"chat": {"id": 42}, "text": "123456"}})
        t.join(3)

    def test_timeout_denies(self):
        d = self.make_daemon(cfg=dict(CFG, approval_ttl_seconds=1))
        result = d.on_shim_request(self.payload(), Peer())  # nobody answers
        self.assertEqual(result["verdict"], "deny")
        self.assertIsNone(result["token"])
        self.assertIn("timed out", result["reason"])

    def test_a_failed_send_denies(self):
        class Broken:
            def send_message(self, *a, **k):
                raise RuntimeError("no network")

        d = gatedaemon.GateDaemon(CFG, Broken(), self.home, patterns=PATTERNS)
        result = d.on_shim_request(self.payload(), Peer())
        self.assertEqual(result["verdict"], "deny")
        self.assertIsNone(result["token"])


if __name__ == "__main__":
    unittest.main()
