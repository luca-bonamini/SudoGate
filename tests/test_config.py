import json
import os
import pathlib
import tempfile
import unittest

from sudogate import config


def write_config(dirpath, data, mode=0o600):
    path = pathlib.Path(dirpath) / "config.json"
    path.write_text(json.dumps(data))
    path.chmod(mode)
    return path


class TestLoad(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def test_defaults_fill_missing_keys(self):
        path = write_config(self.dir, {"bot_token": "T", "chat_id": 42})
        cfg = config.load(path)
        self.assertEqual(cfg["bot_token"], "T")
        self.assertEqual(cfg["chat_id"], 42)
        self.assertEqual(cfg["stop_threshold_seconds"], 120)
        self.assertEqual(cfg["transcript_tail_chars"], 600)
        self.assertFalse(cfg["totp_always"])
        self.assertIsInstance(cfg["destructive_patterns"], list)
        self.assertTrue(cfg["destructive_patterns"])

    def test_explicit_value_beats_default(self):
        path = write_config(self.dir, {"bot_token": "T", "stop_threshold_seconds": 30})
        self.assertEqual(config.load(path)["stop_threshold_seconds"], 30)

    def test_missing_token(self):
        path = write_config(self.dir, {"chat_id": 42})
        with self.assertRaises(config.ConfigError) as ctx:
            config.load(path)
        self.assertIn("bot_token", str(ctx.exception))

    def test_permissions_too_open(self):
        path = write_config(self.dir, {"bot_token": "T"}, mode=0o644)
        with self.assertRaises(config.ConfigError) as ctx:
            config.load(path)
        self.assertIn("0600", str(ctx.exception))

    def test_error_message_omits_token(self):
        path = write_config(self.dir, {"bot_token": "SECRET", "chat_id": 1}, mode=0o644)
        with self.assertRaises(config.ConfigError) as ctx:
            config.load(path)
        self.assertNotIn("SECRET", str(ctx.exception))

    def test_missing_file(self):
        with self.assertRaises(config.ConfigError):
            config.load(pathlib.Path(self.dir) / "does-not-exist.json")

    def test_malformed_json(self):
        path = pathlib.Path(self.dir) / "config.json"
        path.write_text("{not json")
        path.chmod(0o600)
        with self.assertRaises(config.ConfigError):
            config.load(path)


class TestHome(unittest.TestCase):
    def test_env_override_wins(self):
        os.environ["SUDOGATE_HOME"] = "/tmp/sudogate-test-home"
        self.addCleanup(os.environ.pop, "SUDOGATE_HOME", None)
        self.assertEqual(config.home(), pathlib.Path("/tmp/sudogate-test-home"))

    def test_default_is_xdg(self):
        os.environ.pop("SUDOGATE_HOME", None)
        self.assertEqual(config.home(), pathlib.Path.home() / ".config" / "sudogate")


if __name__ == "__main__":
    unittest.main()


class TestSystemPaths(unittest.TestCase):
    """Where the daemon's half lives. None of it is in the gated user's home."""

    def setUp(self):
        for name in ("SUDOGATE_SYSTEM_CONFIG", "SUDOGATE_RUNTIME_DIR"):
            os.environ.pop(name, None)
            self.addCleanup(os.environ.pop, name, None)

    def test_the_daemon_config_is_not_in_a_home_directory(self):
        self.assertEqual(config.system_config_path(), pathlib.Path("/etc/sudogate/config.json"))

    def test_the_runtime_directory_is_not_in_a_home_directory(self):
        self.assertEqual(config.runtime_dir(), pathlib.Path("/run/sudogate"))

    def test_the_socket_lives_in_the_runtime_directory(self):
        self.assertEqual(config.socket_path(), pathlib.Path("/run/sudogate/gate.sock"))

    def test_paths_are_overridable_for_tests(self):
        os.environ["SUDOGATE_RUNTIME_DIR"] = "/tmp/elsewhere"
        self.assertEqual(config.socket_path(), pathlib.Path("/tmp/elsewhere/gate.sock"))


class TestGatedUid(unittest.TestCase):
    def test_an_explicit_uid_is_used(self):
        self.assertEqual(config.gated_uid({"gated_uid": 1000}), 1000)

    def test_a_user_name_is_resolved(self):
        self.assertEqual(config.gated_uid({"gated_user": "root"}), 0)

    def test_an_unknown_user_is_an_error(self):
        with self.assertRaises(config.ConfigError):
            config.gated_uid({"gated_user": "no-such-account-here"})

    def test_neither_is_an_error(self):
        with self.assertRaises(config.ConfigError):
            config.gated_uid({})
