import json
import os
import pathlib
import subprocess
import tempfile
import threading
import unittest

from ctg import ipc

REPO = pathlib.Path(__file__).resolve().parent.parent
HOOK = REPO / "bin" / "claude-tg-hook"


def run_hook(payload_text, ctg_home, timeout=10):
    env = dict(os.environ, CTG_HOME=str(ctg_home), PYTHONPATH=str(REPO))
    return subprocess.run(
        [str(HOOK)],
        input=payload_text,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )


class TestHookEntrypoint(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.received = []
        self.stop = threading.Event()

    def start_daemon(self):
        ready = threading.Event()

        def handler(payload):
            self.received.append(payload)
            return {"sent": True, "reason": "inviato"}

        thread = threading.Thread(
            target=ipc.serve,
            args=(self.home / "sock", handler, self.stop),
            kwargs={"on_ready": ready.set},
            daemon=True,
        )
        thread.start()
        self.assertTrue(ready.wait(5))
        self.addCleanup(thread.join, 5)
        self.addCleanup(self.stop.set)

    def test_inoltra_il_payload_al_daemon(self):
        self.start_daemon()
        result = run_hook(
            json.dumps({"hook_event_name": "Notification", "message": "x"}), self.home
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.received[0]["hook_event_name"], "Notification")

    def test_esce_zero_senza_daemon(self):
        result = run_hook(json.dumps({"hook_event_name": "Stop"}), self.home)
        self.assertEqual(result.returncode, 0)

    def test_non_scrive_su_stdout_senza_daemon(self):
        result = run_hook(json.dumps({"hook_event_name": "Stop"}), self.home)
        self.assertEqual(result.stdout, "")

    def test_kill_switch(self):
        self.start_daemon()
        (self.home / "disabled").touch()
        result = run_hook(
            json.dumps({"hook_event_name": "Notification", "message": "x"}), self.home
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.received, [])

    def test_stdin_non_json(self):
        self.start_daemon()
        result = run_hook("{rotto", self.home)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.received, [])

    def test_stdin_vuoto(self):
        self.start_daemon()
        result = run_hook("", self.home)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.received, [])

    def test_payload_non_oggetto(self):
        self.start_daemon()
        result = run_hook("[1,2,3]", self.home)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.received, [])


if __name__ == "__main__":
    unittest.main()
