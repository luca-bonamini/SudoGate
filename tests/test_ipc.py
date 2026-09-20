import os
import pathlib
import tempfile
import threading
import time
import unittest

from sudogate import ipc


class IPCCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.sock = pathlib.Path(self._tmp.name) / "sock"
        self.stop = threading.Event()
        self.addCleanup(self._tmp.cleanup)

    def start(self, handler, **kwargs):
        ready = threading.Event()

        def run():
            ipc.serve(self.sock, handler, self.stop, on_ready=ready.set, **kwargs)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.assertTrue(ready.wait(5), "the server never started listening")
        self.addCleanup(thread.join, 5)
        self.addCleanup(self.stop.set)
        return thread


class TestIPC(IPCCase):
    def test_round_trip(self):
        self.start(lambda payload, peer: {"echo": payload["value"]})
        self.assertEqual(ipc.request(self.sock, {"value": 7}, timeout=5), {"echo": 7})

    def test_sequential_requests(self):
        self.start(lambda payload, peer: {"n": payload["n"] * 2})
        for n in range(5):
            self.assertEqual(ipc.request(self.sock, {"n": n}, timeout=5), {"n": n * 2})

    def test_socket_is_0600_by_default(self):
        self.start(lambda payload, peer: {})
        self.assertEqual(self.sock.stat().st_mode & 0o777, 0o600)

    def test_socket_mode_is_configurable(self):
        """The daemon opens it wide and relies on the peer check instead: the
        gated user and the daemon do not share a group."""
        self.start(lambda payload, peer: {}, mode=0o666)
        self.assertEqual(self.sock.stat().st_mode & 0o777, 0o666)

    def test_missing_socket(self):
        with self.assertRaises(ipc.IPCError):
            ipc.request(self.sock, {"x": 1}, timeout=1)

    def test_raising_handler_does_not_kill_server(self):
        def handler(payload, peer):
            if payload.get("boom"):
                raise RuntimeError("boom")
            return {"ok": True}

        self.start(handler)
        self.assertIn("error", ipc.request(self.sock, {"boom": True}, timeout=5))
        self.assertEqual(ipc.request(self.sock, {}, timeout=5), {"ok": True})

    def test_client_timeout(self):
        self.start(lambda payload, peer: (time.sleep(3), {"late": True})[1])
        with self.assertRaises(ipc.IPCError):
            ipc.request(self.sock, {}, timeout=0.5)

    def test_stale_socket_is_replaced(self):
        self.sock.write_text("not a socket")
        self.start(lambda payload, peer: {"ok": True})
        self.assertEqual(ipc.request(self.sock, {}, timeout=5), {"ok": True})


class TestPeerCredentials(IPCCase):
    def test_the_handler_is_told_who_is_calling(self):
        seen = {}

        def handler(payload, peer):
            seen["uid"] = peer.uid
            seen["pid"] = peer.pid
            return {"ok": True}

        self.start(handler)
        ipc.request(self.sock, {}, timeout=5)
        self.assertEqual(seen["uid"], os.getuid())
        self.assertEqual(seen["pid"], os.getpid())

    def test_the_gated_uid_is_accepted(self):
        self.start(lambda payload, peer: {"ok": True}, allowed_uids={os.getuid()})
        self.assertEqual(ipc.request(self.sock, {}, timeout=5), {"ok": True})

    def test_any_other_uid_is_refused_before_the_handler_runs(self):
        """A uid cannot be spoofed: SO_PEERCRED is filled in by the kernel.

        The refusal comes before the handler, so no message reaches the phone.
        """
        called = []

        def handler(payload, peer):
            called.append(payload)
            return {"ok": True}

        self.start(handler, allowed_uids={os.getuid() + 1})
        reply = ipc.request(self.sock, {"command": "rm -rf /"}, timeout=5)
        self.assertEqual(reply["verdict"], "deny")
        self.assertIn("not the gated account", reply["reason"])
        self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main()
