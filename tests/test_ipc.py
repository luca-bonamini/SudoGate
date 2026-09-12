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
        self.assertTrue(ready.wait(5), "il server non si è messo in ascolto")
        self.addCleanup(thread.join, 5)
        self.addCleanup(self.stop.set)
        return thread

    def test_andata_e_ritorno(self):
        self.start(lambda payload: {"echo": payload["valore"]})
        self.assertEqual(ipc.request(self.sock, {"valore": 7}, timeout=5), {"echo": 7})

    def test_richieste_in_sequenza(self):
        self.start(lambda payload: {"n": payload["n"] * 2})
        for n in range(5):
            self.assertEqual(ipc.request(self.sock, {"n": n}, timeout=5), {"n": n * 2})

    def test_il_socket_ha_permessi_0600(self):
        self.start(lambda payload: {})
        self.assertEqual(self.sock.stat().st_mode & 0o777, 0o600)

    def test_socket_assente(self):
        with self.assertRaises(ipc.IPCError):
            ipc.request(self.sock, {"x": 1}, timeout=1)

    def test_handler_che_solleva_non_uccide_il_server(self):
        def handler(payload):
            if payload.get("boom"):
                raise RuntimeError("scoppio")
            return {"ok": True}

        self.start(handler)
        self.assertIn("error", ipc.request(self.sock, {"boom": True}, timeout=5))
        self.assertEqual(ipc.request(self.sock, {}, timeout=5), {"ok": True})

    def test_timeout_del_client(self):
        self.start(lambda payload: (time.sleep(3), {"tardi": True})[1])
        with self.assertRaises(ipc.IPCError):
            ipc.request(self.sock, {}, timeout=0.5)

    def test_socket_stantio_viene_rimpiazzato(self):
        self.sock.write_text("non un socket")
        self.start(lambda payload: {"ok": True})
        self.assertEqual(ipc.request(self.sock, {}, timeout=5), {"ok": True})


if __name__ == "__main__":
    unittest.main()
