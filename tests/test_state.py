import pathlib
import tempfile
import unittest

from ctg import state


class StateCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)


class TestCreateAndPeek(StateCase):
    def test_create_ritorna_nonce_url_safe(self):
        nonce = state.create(self.home, "sudo apt update", "/tmp", "personal", now=1000.0)
        self.assertRegex(nonce, r"^[A-Za-z0-9_-]+$")

    def test_peek_restituisce_il_comando(self):
        nonce = state.create(self.home, "sudo apt update", "/tmp", "personal", now=1000.0)
        rec = state.peek(self.home, nonce)
        self.assertEqual(rec["command"], "sudo apt update")
        self.assertEqual(rec["cwd"], "/tmp")
        self.assertEqual(rec["label"], "personal")
        self.assertFalse(rec["used"])

    def test_peek_nonce_inesistente(self):
        self.assertIsNone(state.peek(self.home, "mai-visto"))

    def test_file_di_stato_ha_permessi_0600(self):
        nonce = state.create(self.home, "x", "/tmp", "p", now=1000.0)
        path = self.home / "state" / f"{nonce}.json"
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)


class TestClaim(StateCase):
    def test_claim_valido(self):
        nonce = state.create(self.home, "sudo apt update", "/tmp", "p", now=1000.0)
        rec = state.claim(self.home, nonce, now=1010.0, ttl=120)
        self.assertEqual(rec["command"], "sudo apt update")

    def test_claim_e_monouso(self):
        nonce = state.create(self.home, "x", "/tmp", "p", now=1000.0)
        self.assertIsNotNone(state.claim(self.home, nonce, now=1010.0, ttl=120))
        self.assertIsNone(state.claim(self.home, nonce, now=1011.0, ttl=120))

    def test_claim_scaduto(self):
        nonce = state.create(self.home, "x", "/tmp", "p", now=1000.0)
        self.assertIsNone(state.claim(self.home, nonce, now=1200.0, ttl=120))

    def test_claim_nonce_inesistente(self):
        self.assertIsNone(state.claim(self.home, "mai-visto", now=1.0, ttl=120))

    def test_claim_rifiuta_path_traversal(self):
        (self.home / "state").mkdir()
        (self.home.parent / "segreto.json").write_text('{"command":"x"}')
        for evil in ["../segreto", "a/b", "..", "."]:
            self.assertIsNone(state.claim(self.home, evil, now=1.0, ttl=120))
            self.assertIsNone(state.peek(self.home, evil))


class TestPurge(StateCase):
    def test_purge_rimuove_gli_scaduti(self):
        old = state.create(self.home, "x", "/tmp", "p", now=1000.0)
        new = state.create(self.home, "y", "/tmp", "p", now=1900.0)
        state.purge(self.home, now=2000.0, ttl=120)
        self.assertIsNone(state.peek(self.home, old))
        self.assertIsNotNone(state.peek(self.home, new))


if __name__ == "__main__":
    unittest.main()
