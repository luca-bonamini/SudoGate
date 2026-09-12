import json
import os
import pathlib
import subprocess
import tempfile
import time
import unittest

from sudogate import state, totp

REPO = pathlib.Path(__file__).resolve().parent.parent
WRAPPER = REPO / "bin" / "sudogate-run"
SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


class TestWrapperEntry(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)
        self.home = self.dir / "home"
        self.home.mkdir()
        self.patterns = self.dir / "destructive.patterns"
        self.patterns.write_text(r"\brm\s+(-\w+\s+)*-\w*(r\w*f|f\w*r)" + "\n\\bmkfs\\b\n")
        self.seed = self.dir / "seed"
        self.seed.write_text(SECRET)
        self.audit = self.dir / "audit.log"
        self.always_flag = self.dir / "totp_always"
        self.marker = self.dir / "marker"
        self.addCleanup(self._tmp.cleanup)

    def run_wrapper(self, nonce, code=None, always=False):
        env = dict(
            os.environ,
            PYTHONPATH=str(REPO),
            SUDOGATE_STATE_HOME=str(self.home),
            SUDOGATE_PATTERNS=str(self.patterns),
            SUDOGATE_SEED=str(self.seed),
            SUDOGATE_AUDIT=str(self.audit),
            SUDOGATE_TOTP_ALWAYS=str(self.always_flag if always else self.dir / "absent"),
        )
        args = [str(WRAPPER), nonce] + ([code] if code else [])
        return subprocess.run(args, capture_output=True, text=True, env=env, timeout=10)

    def test_totp_always_denies_a_harmless_command_without_a_code(self):
        self.always_flag.write_text("")
        cmd = f"touch {self.marker}"
        nonce = state.create(self.home, cmd, "/tmp", "p", now=time.time())
        r = self.run_wrapper(nonce, always=True)
        self.assertEqual(r.returncode, 1)
        self.assertFalse(self.marker.exists())  # not executed

    def test_totp_always_runs_a_harmless_command_with_a_valid_code(self):
        self.always_flag.write_text("")
        cmd = f"touch {self.marker}"
        nonce = state.create(self.home, cmd, "/tmp", "p", now=time.time())
        code = totp.generate(SECRET, at_time=time.time())
        r = self.run_wrapper(nonce, code, always=True)
        self.assertEqual(r.returncode, 0)
        self.assertTrue(self.marker.exists())

    def test_non_destructive_runs(self):
        cmd = f"touch {self.marker}"
        nonce = state.create(self.home, cmd, "/tmp", "p", now=time.time())
        r = self.run_wrapper(nonce)
        self.assertEqual(r.returncode, 0)
        self.assertTrue(self.marker.exists())

    def test_destructive_without_code_denied(self):
        cmd = f"rm -rf {self.marker}"
        self.marker.write_text("x")
        nonce = state.create(self.home, cmd, "/tmp", "p", now=time.time())
        r = self.run_wrapper(nonce)
        self.assertEqual(r.returncode, 1)
        self.assertTrue(self.marker.exists())  # not executed

    def test_destructive_with_valid_code_runs(self):
        cmd = f"rm -rf {self.marker}"
        self.marker.mkdir()
        nonce = state.create(self.home, cmd, "/tmp", "p", now=time.time())
        code = totp.generate(SECRET, at_time=time.time())
        r = self.run_wrapper(nonce, code)
        self.assertEqual(r.returncode, 0)
        self.assertFalse(self.marker.exists())  # removed

    def test_reused_nonce_denied(self):
        cmd = f"touch {self.marker}"
        nonce = state.create(self.home, cmd, "/tmp", "p", now=time.time())
        self.assertEqual(self.run_wrapper(nonce).returncode, 0)
        self.assertEqual(self.run_wrapper(nonce).returncode, 1)  # already used

    def test_audit_records(self):
        cmd = f"touch {self.marker}"
        nonce = state.create(self.home, cmd, "/tmp", "p", now=time.time())
        self.run_wrapper(nonce)
        self.assertIn("RUN", self.audit.read_text())


if __name__ == "__main__":
    unittest.main()
