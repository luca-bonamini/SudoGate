import pathlib
import tempfile
import unittest

from sudogate import cache


class CacheCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self._tmp.name) / "cache.json"
        self.addCleanup(self._tmp.cleanup)


class TestCache(CacheCase):
    def test_not_approved_by_default(self):
        self.assertFalse(cache.is_approved(self.path, "/tmp", "apt update", now=1000.0))

    def test_remember_then_approved(self):
        cache.remember(self.path, "/tmp", "apt update", now=1000.0, ttl=8 * 3600)
        self.assertTrue(cache.is_approved(self.path, "/tmp", "apt update", now=1010.0))

    def test_expires_after_ttl(self):
        cache.remember(self.path, "/tmp", "apt update", now=1000.0, ttl=100)
        self.assertFalse(cache.is_approved(self.path, "/tmp", "apt update", now=1101.0))

    def test_different_cwd_does_not_collide(self):
        cache.remember(self.path, "/a", "make", now=1000.0, ttl=1000)
        self.assertFalse(cache.is_approved(self.path, "/b", "make", now=1010.0))

    def test_different_command_does_not_collide(self):
        cache.remember(self.path, "/a", "apt update", now=1000.0, ttl=1000)
        self.assertFalse(cache.is_approved(self.path, "/a", "apt upgrade", now=1010.0))

    def test_exact_match_not_prefix(self):
        cache.remember(self.path, "/a", "apt", now=1000.0, ttl=1000)
        self.assertFalse(cache.is_approved(self.path, "/a", "apt update", now=1010.0))

    def test_corrupt_file_does_not_raise(self):
        self.path.write_text("{broken")
        self.assertFalse(cache.is_approved(self.path, "/a", "x", now=1.0))
        cache.remember(self.path, "/a", "x", now=1.0, ttl=100)
        self.assertTrue(cache.is_approved(self.path, "/a", "x", now=2.0))

    def test_remember_prunes_expired_entries(self):
        cache.remember(self.path, "/a", "old", now=1000.0, ttl=10)
        cache.remember(self.path, "/a", "new", now=2000.0, ttl=10)
        import json
        data = json.loads(self.path.read_text())
        self.assertEqual(len(data), 1)


if __name__ == "__main__":
    unittest.main()
