import pathlib
import tempfile
import threading
import time
import unittest

from sudogate import ipc


class TestIPC(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.sock = pathlib.Path(self._tmp.name) / "sock"
        self.stop = threading.Event()
        self.addCleanup(self._tmp.cleanup)

    def start(self, handler):
        ready = threading.Event()

        def run():
            ipc.serve(self.sock, handler, self.stop, on_ready=ready.set)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.assertTrue(ready.wait(5), "the server never started listening")
        self.addCleanup(thread.join, 5)
        self.addCleanup(self.stop.set)
        return thread

    def test_round_trip(self):
        self.start(lambda payload: {"echo": payload["value"]})
        self.assertEqual(ipc.request(self.sock, {"value": 7}, timeout=5), {"echo": 7})

    def test_sequential_requests(self):
        self.start(lambda payload: {"n": payload["n"] * 2})
        for n in range(5):
            self.assertEqual(ipc.request(self.sock, {"n": n}, timeout=5), {"n": n * 2})

    def test_socket_is_0600(self):
        self.start(lambda payload: {})
        self.assertEqual(self.sock.stat().st_mode & 0o777, 0o600)

    def test_missing_socket(self):
        with self.assertRaises(ipc.IPCError):
            ipc.request(self.sock, {"x": 1}, timeout=1)

    def test_raising_handler_does_not_kill_server(self):
        def handler(payload):
            if payload.get("boom"):
                raise RuntimeError("boom")
            return {"ok": True}

        self.start(handler)
        self.assertIn("error", ipc.request(self.sock, {"boom": True}, timeout=5))
        self.assertEqual(ipc.request(self.sock, {}, timeout=5), {"ok": True})

    def test_client_timeout(self):
        self.start(lambda payload: (time.sleep(3), {"late": True})[1])
        with self.assertRaises(ipc.IPCError):
            ipc.request(self.sock, {}, timeout=0.5)

    def test_stale_socket_is_replaced(self):
        self.sock.write_text("not a socket")
        self.start(lambda payload: {"ok": True})
        self.assertEqual(ipc.request(self.sock, {}, timeout=5), {"ok": True})


if __name__ == "__main__":
    unittest.main()
