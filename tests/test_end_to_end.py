"""The whole chain, minus sudo: shim -> socket -> daemon -> record -> wrapper.

What these cover is the property the redesign is for: the command the owner
sees on the phone is the command root runs, and nothing the shim says changes
the decision. The shim's call to sudo is replaced by a direct call to the real
wrapper, which is the only step that needs privilege in production.
"""
import importlib.util
import os
import pathlib
import subprocess
import tempfile
import threading
import time
import unittest

from sudogate import gatedaemon, ipc, state, totp

REPO = pathlib.Path(__file__).resolve().parent.parent
SHIM = REPO / "bin" / "sudogate"
WRAPPER = REPO / "bin" / "sudogate-run"
SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
PATTERNS = [r"\brm\s+(-\w+\s+)*-\w*(r\w*f|f\w*r)"]


def _load(path, name):
    module = importlib.util.module_from_spec(
        importlib.util.spec_from_loader(name, loader=None, origin=str(path))
    )
    module.__file__ = str(path)
    exec(compile(path.read_text(), str(path), "exec"), module.__dict__)
    return module


class FakeClient:
    def __init__(self):
        self.sent = []

    def send_message(self, chat_id, text, buttons=None):
        self.sent.append((chat_id, text, buttons))
        return {"message_id": len(self.sent)}


class EndToEndCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.runtime = self.dir / "run"
        self.runtime.mkdir()
        self.patterns = self.dir / "destructive.patterns"
        self.patterns.write_text("\n".join(PATTERNS))
        self.seed = self.dir / "seed"
        self.seed.write_text(SECRET)
        self.audit = self.dir / "audit.log"
        self.marker = self.dir / "marker"
        self.always_flag = self.dir / "absent"

        self.client = FakeClient()
        self.daemon = gatedaemon.GateDaemon(
            {"bot_token": "T", "chat_id": 42, "approval_ttl_seconds": 5},
            self.client, self.runtime, patterns=PATTERNS,
            cache_path=self.dir / "cache.json",
        )
        self.sock = self.runtime / "gate.sock"
        self.stop = threading.Event()
        ready = threading.Event()
        thread = threading.Thread(
            target=ipc.serve, args=(self.sock, self.daemon.on_shim_request, self.stop),
            kwargs={"on_ready": ready.set, "allowed_uids": {os.getuid()}, "mode": 0o666},
            daemon=True,
        )
        thread.start()
        self.assertTrue(ready.wait(5))
        self.addCleanup(thread.join, 5)
        self.addCleanup(self.stop.set)

        os.environ["SUDOGATE_RUNTIME_DIR"] = str(self.runtime)
        self.addCleanup(os.environ.pop, "SUDOGATE_RUNTIME_DIR", None)
        self.shim = _load(SHIM, "sudogate_shim")
        self.shim.subprocess = _SudoStub(self)

    def wrapper_env(self):
        return dict(
            os.environ,
            PYTHONPATH=str(REPO),
            SUDOGATE_RUNTIME_DIR=str(self.runtime),
            SUDOGATE_PATTERNS=str(self.patterns),
            SUDOGATE_SEED=str(self.seed),
            SUDOGATE_AUDIT=str(self.audit),
            SUDOGATE_TOTP_ALWAYS=str(self.always_flag),
            SUDO_UID=str(os.getuid()),
        )

    def run_shim(self, argv):
        result = {}
        t = threading.Thread(target=lambda: result.update(code=self.shim.main(argv)))
        t.start()
        return result, t

    def wait_pending(self):
        for _ in range(150):
            with self.daemon._lock:
                if self.daemon._pending:
                    return next(iter(self.daemon._pending))
            time.sleep(0.02)
        self.fail("the daemon never registered the request")

    def tap(self, nonce, action="a"):
        self.daemon.on_update(
            {"callback_query": {"message": {"chat": {"id": 42}}, "data": f"{action}:{nonce}"}}
        )

    def send_code(self, code):
        self.daemon.on_update({"message": {"chat": {"id": 42}, "text": code}})


class _SudoStub:
    """Stands in for `sudo sudogate-run <token>`, which the tests cannot run."""

    def __init__(self, case):
        self.case = case
        self.calls = []

    def run(self, args, **kwargs):
        self.calls.append(args)
        self.case.assertEqual(args[0], "sudo")
        self.case.assertEqual(args[1], "/usr/local/sbin/sudogate-run")
        return subprocess.run(
            [str(WRAPPER)] + list(args[2:]),
            capture_output=True, text=True, env=self.case.wrapper_env(), timeout=10,
        )


class TestApprovedRun(EndToEndCase):
    def test_a_harmless_command_runs_after_one_tap(self):
        result, t = self.run_shim(["touch", str(self.marker)])
        self.tap(self.wait_pending())
        t.join(10)
        self.assertEqual(result["code"], 0)
        self.assertTrue(self.marker.exists())

    def test_the_phone_is_shown_the_command_that_runs(self):
        result, t = self.run_shim(["touch", str(self.marker)])
        self.tap(self.wait_pending())
        t.join(10)
        sent_text = self.client.sent[0][1]
        self.assertIn(f"touch {self.marker}", sent_text)
        self.assertIn(f"touch {self.marker}", self.audit.read_text())

    def test_a_denied_command_does_not_run(self):
        result, t = self.run_shim(["touch", str(self.marker)])
        self.tap(self.wait_pending(), action="n")
        t.join(10)
        self.assertEqual(result["code"], 1)
        self.assertFalse(self.marker.exists())

    def test_a_destructive_command_needs_the_code_from_the_phone(self):
        self.marker.mkdir()
        result, t = self.run_shim(["rm", "-rf", str(self.marker)])
        nonce = self.wait_pending()
        self.tap(nonce)
        self.send_code(totp.generate(SECRET, at_time=time.time()))
        t.join(10)
        self.assertEqual(result["code"], 0)
        self.assertFalse(self.marker.exists())

    def test_a_wrong_code_denies_at_the_root_end(self):
        self.marker.mkdir()
        result, t = self.run_shim(["rm", "-rf", str(self.marker)])
        self.tap(self.wait_pending())
        self.send_code("000000")
        t.join(10)
        self.assertEqual(result["code"], 1)
        self.assertTrue(self.marker.exists())

    def test_quoting_survives_the_round_trip(self):
        target = self.dir / "two words"
        result, t = self.run_shim(["touch", str(target)])
        self.tap(self.wait_pending())
        t.join(10)
        self.assertTrue(target.exists())


class TestForgery(EndToEndCase):
    def test_a_record_the_daemon_never_wrote_has_no_token_to_spend(self):
        """The gated user can no longer mint one: in production the directory
        is 0700 under the daemon's account. Here the point is narrower — a
        token only exists once the daemon has written the record."""
        before = list((self.runtime / state.SUBDIR).glob("*.json")) \
            if (self.runtime / state.SUBDIR).is_dir() else []
        result, t = self.run_shim(["touch", str(self.marker)])
        self.tap(self.wait_pending(), action="n")
        t.join(10)
        after = list((self.runtime / state.SUBDIR).glob("*.json")) \
            if (self.runtime / state.SUBDIR).is_dir() else []
        self.assertEqual(before, after)

    def test_the_shim_sends_no_verdict_of_its_own(self):
        seen = {}
        original = self.daemon.on_shim_request

        def spy(payload, peer):
            seen.update(payload)
            return original(payload, peer)

        self.stop.set()
        stop = threading.Event()
        ready = threading.Event()
        sock = self.runtime / "spy.sock"
        thread = threading.Thread(
            target=ipc.serve, args=(sock, spy, stop),
            kwargs={"on_ready": ready.set, "allowed_uids": {os.getuid()}, "mode": 0o666},
            daemon=True,
        )
        thread.start()
        self.assertTrue(ready.wait(5))
        self.addCleanup(thread.join, 5)
        self.addCleanup(stop.set)

        # Drive the shim, so the payload inspected is the one it really sends.
        self.shim.config.socket_path = lambda: sock
        result, t = self.run_shim(["apt", "update"])
        self.tap(self.wait_pending())
        t.join(10)
        self.assertEqual(sorted(seen), ["command", "cwd", "label"])
        self.assertNotIn("destructive", seen)
        self.assertNotIn("nonce", seen)
        self.assertNotIn("token", seen)


if __name__ == "__main__":
    unittest.main()
