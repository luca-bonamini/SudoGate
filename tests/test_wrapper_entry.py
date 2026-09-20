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


class WrapperEntryCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)
        self.runtime = self.dir / "run"
        self.runtime.mkdir()
        self.patterns = self.dir / "destructive.patterns"
        self.patterns.write_text(r"\brm\s+(-\w+\s+)*-\w*(r\w*f|f\w*r)" + "\n\\bmkfs\\b\n")
        self.seed = self.dir / "seed"
        self.seed.write_text(SECRET)
        self.audit = self.dir / "audit.log"
        self.always_flag = self.dir / "totp_always"
        self.marker = self.dir / "marker"
        self.addCleanup(self._tmp.cleanup)

    def approve(self, command, totp_code=None, uid=None, now=None):
        """Stand in for the daemon: write the record it would write."""
        return state.create(
            self.runtime, command, "/tmp", "p",
            now=time.time() if now is None else now,
            uid=os.getuid() if uid is None else uid,
            totp=totp_code,
        )

    def run_wrapper(self, token, always=False, sudo_uid=None):
        env = dict(
            os.environ,
            PYTHONPATH=str(REPO),
            SUDOGATE_RUNTIME_DIR=str(self.runtime),
            SUDOGATE_PATTERNS=str(self.patterns),
            SUDOGATE_SEED=str(self.seed),
            SUDOGATE_AUDIT=str(self.audit),
            SUDOGATE_TOTP_ALWAYS=str(self.always_flag if always else self.dir / "absent"),
            SUDO_UID=str(os.getuid() if sudo_uid is None else sudo_uid),
        )
        return subprocess.run(
            [str(WRAPPER), token], capture_output=True, text=True, env=env, timeout=10
        )


class TestAuthorisation(WrapperEntryCase):
    def test_non_destructive_runs(self):
        token = self.approve(f"touch {self.marker}")
        self.assertEqual(self.run_wrapper(token).returncode, 0)
        self.assertTrue(self.marker.exists())

    def test_destructive_without_a_code_is_denied(self):
        self.marker.write_text("x")
        token = self.approve(f"rm -rf {self.marker}")
        self.assertEqual(self.run_wrapper(token).returncode, 1)
        self.assertTrue(self.marker.exists())  # not executed

    def test_destructive_with_a_valid_code_runs(self):
        self.marker.mkdir()
        token = self.approve(f"rm -rf {self.marker}", totp_code=totp.generate(SECRET, at_time=time.time()))
        self.assertEqual(self.run_wrapper(token).returncode, 0)
        self.assertFalse(self.marker.exists())

    def test_destructive_with_a_wrong_code_is_denied(self):
        self.marker.mkdir()
        token = self.approve(f"rm -rf {self.marker}", totp_code="000000")
        self.assertEqual(self.run_wrapper(token).returncode, 1)
        self.assertTrue(self.marker.exists())

    def test_totp_always_denies_a_harmless_command_without_a_code(self):
        self.always_flag.write_text("")
        token = self.approve(f"touch {self.marker}")
        self.assertEqual(self.run_wrapper(token, always=True).returncode, 1)
        self.assertFalse(self.marker.exists())

    def test_totp_always_runs_a_harmless_command_with_a_valid_code(self):
        self.always_flag.write_text("")
        token = self.approve(f"touch {self.marker}",
                             totp_code=totp.generate(SECRET, at_time=time.time()))
        self.assertEqual(self.run_wrapper(token, always=True).returncode, 0)
        self.assertTrue(self.marker.exists())

    def test_the_command_is_reclassified_here(self):
        """The record says nothing about being destructive, and could not be
        believed if it did: the patterns are the root-owned ones."""
        self.marker.mkdir()
        token = self.approve(f"rm -rf {self.marker}")
        result = self.run_wrapper(token)
        self.assertEqual(result.returncode, 1)
        self.assertIn("TOTP", result.stderr)


class TestTokenHandling(WrapperEntryCase):
    def test_a_used_token_is_refused(self):
        token = self.approve(f"touch {self.marker}")
        self.assertEqual(self.run_wrapper(token).returncode, 0)
        self.assertEqual(self.run_wrapper(token).returncode, 1)

    def test_an_unknown_token_is_refused(self):
        self.assertEqual(self.run_wrapper("never-issued").returncode, 1)

    def test_an_expired_token_is_refused(self):
        token = self.approve(f"touch {self.marker}", now=time.time() - 400)
        self.assertEqual(self.run_wrapper(token).returncode, 1)
        self.assertFalse(self.marker.exists())

    def test_no_argument_is_a_usage_error(self):
        env = dict(os.environ, PYTHONPATH=str(REPO), SUDOGATE_RUNTIME_DIR=str(self.runtime))
        result = subprocess.run([str(WRAPPER)], capture_output=True, text=True, env=env, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn("usage:", result.stderr)

    def test_the_record_is_removed_after_a_run(self):
        token = self.approve(f"touch {self.marker}")
        self.run_wrapper(token)
        self.assertIsNone(state.peek(self.runtime, token))

    def test_a_denied_record_is_removed_too(self):
        self.marker.write_text("x")
        token = self.approve(f"rm -rf {self.marker}")
        self.run_wrapper(token)
        self.assertIsNone(state.peek(self.runtime, token))


class TestCallerBinding(WrapperEntryCase):
    def test_another_account_cannot_spend_the_approval(self):
        token = self.approve(f"touch {self.marker}", uid=os.getuid() + 1)
        result = self.run_wrapper(token)
        self.assertEqual(result.returncode, 1)
        self.assertIn("another account", result.stderr)
        self.assertFalse(self.marker.exists())

    def test_the_approved_account_can(self):
        token = self.approve(f"touch {self.marker}", uid=os.getuid())
        self.assertEqual(self.run_wrapper(token).returncode, 0)
        self.assertTrue(self.marker.exists())


class TestAudit(WrapperEntryCase):
    def test_a_run_is_recorded(self):
        token = self.approve(f"touch {self.marker}")
        self.run_wrapper(token)
        self.assertIn("RUN", self.audit.read_text())

    def test_a_denial_is_recorded(self):
        self.marker.write_text("x")
        token = self.approve(f"rm -rf {self.marker}")
        self.run_wrapper(token)
        self.assertIn("DENY", self.audit.read_text())

    def test_a_uid_mismatch_is_recorded(self):
        token = self.approve(f"touch {self.marker}", uid=os.getuid() + 1)
        self.run_wrapper(token)
        self.assertIn("uid-mismatch", self.audit.read_text())


if __name__ == "__main__":
    unittest.main()
