import pathlib
import tempfile
import unittest

from sudogate import totp, wrapper

SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
PATTERNS = [r"\brm\s+(-\w+\s+)*-\w*(r\w*f|f\w*r)", r"\bmkfs\b", r"/etc/netplan"]


class TestAuthorize(unittest.TestCase):
    def test_non_destructive_passes_without_totp(self):
        ok, _ = wrapper.authorize("apt update", PATTERNS, SECRET, totp_code=None, now=59)
        self.assertTrue(ok)

    def test_destructive_requires_valid_totp(self):
        code = totp.generate(SECRET, at_time=59)
        ok, _ = wrapper.authorize("rm -rf /x", PATTERNS, SECRET, totp_code=code, now=59)
        self.assertTrue(ok)

    def test_destructive_with_wrong_totp_denied(self):
        ok, reason = wrapper.authorize("rm -rf /x", PATTERNS, SECRET, totp_code="000000", now=59)
        self.assertFalse(ok)
        self.assertIn("TOTP", reason)

    def test_destructive_without_totp_denied(self):
        ok, _ = wrapper.authorize("mkfs.ext4 /dev/sdb", PATTERNS, SECRET, totp_code=None, now=59)
        self.assertFalse(ok)

    def test_destructive_without_seed_denied(self):
        ok, reason = wrapper.authorize("rm -rf /x", PATTERNS, seed=None, totp_code="123456", now=59)
        self.assertFalse(ok)
        self.assertIn("seed", reason)


class TestTotpAlways(unittest.TestCase):
    """The policy requiring a code for every command, not only destructive ones."""

    def test_non_destructive_needs_totp_when_always(self):
        ok, reason = wrapper.authorize(
            "apt update", PATTERNS, SECRET, totp_code=None, now=59, always=True
        )
        self.assertFalse(ok)
        self.assertIn("TOTP", reason)

    def test_non_destructive_runs_with_valid_code_when_always(self):
        code = totp.generate(SECRET, at_time=59)
        ok, _ = wrapper.authorize(
            "apt update", PATTERNS, SECRET, totp_code=code, now=59, always=True
        )
        self.assertTrue(ok)

    def test_wrong_code_denied_when_always(self):
        ok, _ = wrapper.authorize(
            "apt update", PATTERNS, SECRET, totp_code="000000", now=59, always=True
        )
        self.assertFalse(ok)

    def test_requires_totp(self):
        self.assertFalse(wrapper.requires_totp("apt update", PATTERNS, always=False))
        self.assertTrue(wrapper.requires_totp("apt update", PATTERNS, always=True))
        self.assertTrue(wrapper.requires_totp("rm -rf /x", PATTERNS, always=False))


class TestLoaders(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_load_patterns_one_per_line(self):
        p = self.dir / "destructive.patterns"
        p.write_text("# a comment\n\\bmkfs\\b\n\n/etc/netplan\n")
        pats = wrapper.load_patterns(p)
        self.assertEqual(pats, ["\\bmkfs\\b", "/etc/netplan"])

    def test_load_patterns_falls_back_to_defaults(self):
        pats = wrapper.load_patterns(self.dir / "missing")
        self.assertTrue(pats)  # falls back to config DEFAULTS, never an empty list

    def test_load_seed(self):
        p = self.dir / "seed"
        p.write_text(SECRET + "\n")
        self.assertEqual(wrapper.load_seed(p), SECRET)

    def test_load_seed_missing(self):
        self.assertIsNone(wrapper.load_seed(self.dir / "missing"))

    def test_load_totp_always(self):
        flag = self.dir / "totp_always"
        self.assertFalse(wrapper.load_totp_always(flag))
        flag.write_text("")
        self.assertTrue(wrapper.load_totp_always(flag))


if __name__ == "__main__":
    unittest.main()
