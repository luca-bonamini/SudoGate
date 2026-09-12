import pathlib
import tempfile
import threading
import unittest

from ctg import gatedaemon


class FakeClient:
    def __init__(self):
        self.sent = []
        self._id = 0

    def send_message(self, chat_id, text, buttons=None):
        self._id += 1
        self.sent.append((chat_id, text, buttons))
        return {"message_id": self._id}


CFG = {"bot_token": "T", "chat_id": 42, "approval_ttl_seconds": 5}


class GateDaemonCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.client = FakeClient()
        self.d = gatedaemon.GateDaemon(CFG, self.client, self.home)

    def payload(self, destructive=False, nonce="N1"):
        return {"nonce": nonce, "command": "rm -rf /x" if destructive else "apt update",
                "cwd": "/tmp", "label": "personal", "destructive": destructive}


class TestNonDestructive(GateDaemonCase):
    def test_approva_con_bottone(self):
        p = self.payload()
        result = {}
        t = threading.Thread(target=lambda: result.update(self.d.on_shim_request(p)))
        t.start()
        self._wait_pending("N1")
        self.d.on_update({"callback_query": {"message": {"chat": {"id": 42}}, "data": "a:N1"}})
        t.join(3)
        self.assertEqual(result["verdict"], "approve")
        self.assertIsNone(result["totp"])

    def test_nega_con_bottone(self):
        p = self.payload()
        result = {}
        t = threading.Thread(target=lambda: result.update(self.d.on_shim_request(p)))
        t.start()
        self._wait_pending("N1")
        self.d.on_update({"callback_query": {"message": {"chat": {"id": 42}}, "data": "n:N1"}})
        t.join(3)
        self.assertEqual(result["verdict"], "deny")

    def _wait_pending(self, nonce):
        import time
        for _ in range(50):
            with self.d._lock:
                if nonce in self.d._pending:
                    return
            time.sleep(0.02)
        self.fail("pending mai registrato")


class TestDestructive(GateDaemonCase):
    def test_approva_poi_chiede_e_riceve_totp(self):
        p = self.payload(destructive=True)
        result = {}
        t = threading.Thread(target=lambda: result.update(self.d.on_shim_request(p)))
        t.start()
        self._wait_pending("N1")
        # primo tap: non risolve, chiede le cifre
        self.d.on_update({"callback_query": {"message": {"chat": {"id": 42}}, "data": "a:N1"}})
        with self.d._lock:
            self.assertTrue(self.d._pending["N1"].awaiting_totp)
        # invio codice
        self.d.on_update({"message": {"chat": {"id": 42}, "text": "123456"}})
        t.join(3)
        self.assertEqual(result["verdict"], "approve")
        self.assertEqual(result["totp"], "123456")

    def _wait_pending(self, nonce):
        import time
        for _ in range(50):
            with self.d._lock:
                if nonce in self.d._pending:
                    return
            time.sleep(0.02)
        self.fail("pending mai registrato")


class TestSecurity(GateDaemonCase):
    def test_scarta_callback_chat_estranea(self):
        p = self.payload()
        result = {}
        t = threading.Thread(target=lambda: result.update(self.d.on_shim_request(p)))
        t.start()
        self._wait_pending("N1")
        self.d.on_update({"callback_query": {"message": {"chat": {"id": 999}}, "data": "a:N1"}})
        import time
        time.sleep(0.3)
        with self.d._lock:
            self.assertIn("N1", self.d._pending)  # non risolto
        # risolvo per far terminare il thread
        self.d.on_update({"callback_query": {"message": {"chat": {"id": 42}}, "data": "n:N1"}})
        t.join(3)
        self.assertEqual(result["verdict"], "deny")

    def test_timeout_nega(self):
        cfg = dict(CFG, approval_ttl_seconds=1)
        d = gatedaemon.GateDaemon(cfg, self.client, self.home)
        result = d.on_shim_request(self.payload())  # nessuno risponde
        self.assertEqual(result["verdict"], "deny")
        self.assertIn("timeout", result["reason"])

    def _wait_pending(self, nonce):
        import time
        for _ in range(50):
            with self.d._lock:
                if nonce in self.d._pending:
                    return
            time.sleep(0.02)
        self.fail("pending mai registrato")


if __name__ == "__main__":
    unittest.main()
