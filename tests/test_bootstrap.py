import json
import pathlib
import tempfile
import unittest

from sudogate import bootstrap, config


class TestFirstChatId(unittest.TestCase):
    def test_takes_the_first_message(self):
        updates = [
            {"update_id": 1, "message": {"chat": {"id": 77}, "text": "/start"}},
            {"update_id": 2, "message": {"chat": {"id": 88}, "text": "ciao"}},
        ]
        self.assertEqual(bootstrap.first_chat_id(updates), 77)

    def test_ignores_update_without_chat(self):
        self.assertEqual(
            bootstrap.first_chat_id(
                [{"update_id": 1}, {"update_id": 2, "message": {"chat": {"id": 5}}}]
            ),
            5,
        )

    def test_no_message(self):
        self.assertIsNone(bootstrap.first_chat_id([]))


class TestWriteConfig(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self._tmp.name) / "config.json"
        self.addCleanup(self._tmp.cleanup)

    def test_writes_with_0600(self):
        bootstrap.write_config(self.path, "TOK", 77)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_written_file_is_loadable(self):
        bootstrap.write_config(self.path, "TOK", 77)
        cfg = config.load(self.path)
        self.assertEqual(cfg["bot_token"], "TOK")
        self.assertEqual(cfg["chat_id"], 77)

    def test_preserves_existing_keys(self):
        self.path.write_text(json.dumps({"stop_threshold_seconds": 45}))
        self.path.chmod(0o600)
        bootstrap.write_config(self.path, "TOK", 77)
        self.assertEqual(config.load(self.path)["stop_threshold_seconds"], 45)


if __name__ == "__main__":
    unittest.main()
