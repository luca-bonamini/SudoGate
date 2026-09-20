import json
import pathlib
import tempfile
import unittest

from sudogate import state


class StateCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)


class TestCreateAndPeek(StateCase):
    def test_create_returns_url_safe_token(self):
        token = state.create(self.home, "sudo apt update", "/tmp", "personal", now=1000.0)
        self.assertRegex(token, r"^[A-Za-z0-9_-]+$")

    def test_peek_returns_the_command(self):
        token = state.create(self.home, "sudo apt update", "/tmp", "personal", now=1000.0)
        rec = state.peek(self.home, token)
        self.assertEqual(rec["command"], "sudo apt update")
        self.assertEqual(rec["cwd"], "/tmp")
        self.assertEqual(rec["label"], "personal")
        self.assertFalse(rec["used"])

    def test_the_record_carries_the_uid_and_the_code(self):
        token = state.create(self.home, "x", "/tmp", "p", now=1000.0, uid=1000, totp="123456")
        rec = state.peek(self.home, token)
        self.assertEqual(rec["uid"], 1000)
        self.assertEqual(rec["totp"], "123456")

    def test_peek_unknown_token(self):
        self.assertIsNone(state.peek(self.home, "never-seen"))

    def test_record_file_is_0600(self):
        token = state.create(self.home, "x", "/tmp", "p", now=1000.0)
        path = self.home / state.SUBDIR / f"{token}.json"
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_directory_is_0700(self):
        """The gated user must not be able to read a token, or list one."""
        state.create(self.home, "x", "/tmp", "p", now=1000.0)
        self.assertEqual((self.home / state.SUBDIR).stat().st_mode & 0o777, 0o700)


class TestClaim(StateCase):
    def test_valid_claim(self):
        token = state.create(self.home, "sudo apt update", "/tmp", "p", now=1000.0)
        rec = state.claim(self.home, token, now=1010.0, ttl=120)
        self.assertEqual(rec["command"], "sudo apt update")

    def test_claim_is_single_use(self):
        token = state.create(self.home, "x", "/tmp", "p", now=1000.0)
        self.assertIsNotNone(state.claim(self.home, token, now=1010.0, ttl=120))
        self.assertIsNone(state.claim(self.home, token, now=1011.0, ttl=120))

    def test_expired_claim(self):
        token = state.create(self.home, "x", "/tmp", "p", now=1000.0)
        self.assertIsNone(state.claim(self.home, token, now=1200.0, ttl=120))

    def test_claim_unknown_token(self):
        self.assertIsNone(state.claim(self.home, "never-seen", now=1.0, ttl=120))

    def test_claim_rejects_path_traversal(self):
        (self.home / state.SUBDIR).mkdir()
        (self.home.parent / "secret.json").write_text('{"command":"x"}')
        for evil in ["../secret", "a/b", "..", "."]:
            self.assertIsNone(state.claim(self.home, evil, now=1.0, ttl=120))
            self.assertIsNone(state.peek(self.home, evil))


class TestDiscard(StateCase):
    def test_discard_removes_the_record(self):
        token = state.create(self.home, "x", "/tmp", "p", now=1000.0)
        state.discard(self.home, token)
        self.assertIsNone(state.peek(self.home, token))

    def test_discard_ignores_an_invalid_token(self):
        state.discard(self.home, "../escape")  # must not raise, must not traverse
        self.assertFalse((self.home.parent / "escape.json").exists())


class TestPurge(StateCase):
    def test_purge_removes_expired(self):
        old = state.create(self.home, "x", "/tmp", "p", now=1000.0)
        new = state.create(self.home, "y", "/tmp", "p", now=1900.0)
        state.purge(self.home, now=2000.0, ttl=120)
        self.assertIsNone(state.peek(self.home, old))
        self.assertIsNotNone(state.peek(self.home, new))

    def test_purge_removes_unreadable_records(self):
        d = self.home / state.SUBDIR
        d.mkdir(parents=True)
        junk = d / "junk.json"
        junk.write_text("not json")
        state.purge(self.home, now=1.0, ttl=120)
        self.assertFalse(junk.exists())

    def test_purge_keeps_valid_json(self):
        d = self.home / state.SUBDIR
        d.mkdir(parents=True)
        (d / "keep.json").write_text(json.dumps({"created_at": 1000.0, "command": "x"}))
        state.purge(self.home, now=1010.0, ttl=120)
        self.assertTrue((d / "keep.json").exists())


if __name__ == "__main__":
    unittest.main()
