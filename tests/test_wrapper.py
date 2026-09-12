import pathlib
import tempfile
import unittest

from ctg import totp, wrapper

SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
PATTERNS = [r"\brm\s+(-\w+\s+)*-\w*(r\w*f|f\w*r)", r"\bmkfs\b", r"/etc/netplan"]


class TestAuthorize(unittest.TestCase):
    def test_non_distruttivo_passa_senza_totp(self):
        ok, _ = wrapper.authorize("apt update", PATTERNS, SECRET, totp_code=None, now=59)
        self.assertTrue(ok)

    def test_distruttivo_richiede_totp_valido(self):
        code = totp.generate(SECRET, at_time=59)
        ok, _ = wrapper.authorize("rm -rf /x", PATTERNS, SECRET, totp_code=code, now=59)
        self.assertTrue(ok)

    def test_distruttivo_con_totp_sbagliato_negato(self):
        ok, reason = wrapper.authorize("rm -rf /x", PATTERNS, SECRET, totp_code="000000", now=59)
        self.assertFalse(ok)
        self.assertIn("TOTP", reason)

    def test_distruttivo_senza_totp_negato(self):
        ok, _ = wrapper.authorize("mkfs.ext4 /dev/sdb", PATTERNS, SECRET, totp_code=None, now=59)
        self.assertFalse(ok)

    def test_distruttivo_senza_seed_negato(self):
        ok, reason = wrapper.authorize("rm -rf /x", PATTERNS, seed=None, totp_code="123456", now=59)
        self.assertFalse(ok)
        self.assertIn("seed", reason)


class TestLoaders(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_load_patterns_una_per_riga(self):
        p = self.dir / "destructive.patterns"
        p.write_text("# commento\n\\bmkfs\\b\n\n/etc/netplan\n")
        pats = wrapper.load_patterns(p)
        self.assertEqual(pats, ["\\bmkfs\\b", "/etc/netplan"])

    def test_load_patterns_file_assente_ritorna_default_config(self):
        pats = wrapper.load_patterns(self.dir / "manca")
        self.assertTrue(pats)  # cade sui DEFAULTS di config, mai lista vuota

    def test_load_seed(self):
        p = self.dir / "seed"
        p.write_text(SECRET + "\n")
        self.assertEqual(wrapper.load_seed(p), SECRET)

    def test_load_seed_assente(self):
        self.assertIsNone(wrapper.load_seed(self.dir / "manca"))


if __name__ == "__main__":
    unittest.main()
