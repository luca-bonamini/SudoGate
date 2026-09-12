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
    def test_create_returns_url_safe_nonce(self):
        nonce = state.create(self.home, "sudo apt update", "/tmp", "personal", now=1000.0)
        self.assertRegex(nonce, r"^[A-Za-z0-9_-]+$")

    def test_peek_returns_the_command(self):
        nonce = state.create(self.home, "sudo apt update", "/tmp", "personal", now=1000.0)
        rec = state.peek(self.home, nonce)
        self.assertEqual(rec["command"], "sudo apt update")
        self.assertEqual(rec["cwd"], "/tmp")
        self.assertEqual(rec["label"], "personal")
        self.assertFalse(rec["used"])

    def test_peek_unknown_nonce(self):
        self.assertIsNone(state.peek(self.home, "never-seen"))

    def test_state_file_is_0600(self):
        nonce = state.create(self.home, "x", "/tmp", "p", now=1000.0)
        path = self.home / "state" / f"{nonce}.json"
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)


class TestClaim(StateCase):
    def test_valid_claim(self):
        nonce = state.create(self.home, "sudo apt update", "/tmp", "p", now=1000.0)
        rec = state.claim(self.home, nonce, now=1010.0, ttl=120)
        self.assertEqual(rec["command"], "sudo apt update")

    def test_claim_is_single_use(self):
        nonce = state.create(self.home, "x", "/tmp", "p", now=1000.0)
        self.assertIsNotNone(state.claim(self.home, nonce, now=1010.0, ttl=120))
        self.assertIsNone(state.claim(self.home, nonce, now=1011.0, ttl=120))

    def test_expired_claim(self):
        nonce = state.create(self.home, "x", "/tmp", "p", now=1000.0)
        self.assertIsNone(state.claim(self.home, nonce, now=1200.0, ttl=120))

    def test_claim_unknown_nonce(self):
        self.assertIsNone(state.claim(self.home, "never-seen", now=1.0, ttl=120))

    def test_claim_rejects_path_traversal(self):
        (self.home / "state").mkdir()
        (self.home.parent / "secret.json").write_text('{"command":"x"}')
        for evil in ["../secret", "a/b", "..", "."]:
            self.assertIsNone(state.claim(self.home, evil, now=1.0, ttl=120))
            self.assertIsNone(state.peek(self.home, evil))


class TestPurge(StateCase):
    def test_purge_removes_expired(self):
        old = state.create(self.home, "x", "/tmp", "p", now=1000.0)
        new = state.create(self.home, "y", "/tmp", "p", now=1900.0)
        state.purge(self.home, now=2000.0, ttl=120)
        self.assertIsNone(state.peek(self.home, old))
        self.assertIsNotNone(state.peek(self.home, new))


if __name__ == "__main__":
    unittest.main()
