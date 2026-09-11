import pathlib
import tempfile
import unittest

from ctg import daemon, turns


class FakeClient:
    def __init__(self):
        self.sent = []

    def send_message(self, chat_id, text, buttons=None):
        self.sent.append((chat_id, text, buttons))
        return {"message_id": len(self.sent)}


BASE_CONFIG = {
    "bot_token": "T",
    "chat_id": 42,
    "stop_threshold_seconds": 120,
    "transcript_tail_chars": 600,
}


class DaemonCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.client = FakeClient()
        self.clock = turns.TurnClock(self.dir / "turns.json")

    def make(self, transcript_text=None):
        return daemon.Daemon(
            cfg=dict(BASE_CONFIG),
            client=self.client,
            clock=self.clock,
            sessions_reader=lambda: {"rc-crm": "/home/luca/Project/MayBeCompany/CRM"},
            transcript_reader=lambda path, max_chars: transcript_text,
        )


class TestHandleHook(DaemonCase):
    def test_notification_manda_sempre(self):
        result = self.make().handle_hook(
            {
                "hook_event_name": "Notification",
                "cwd": "/home/luca/Project/MayBeCompany/CRM",
                "session_id": "s1",
                "message": "serve un permesso",
            }
        )
        self.assertTrue(result["sent"])
        self.assertEqual(self.client.sent[0][0], 42)
        self.assertIn("crm", self.client.sent[0][1])
        self.assertIn("serve un permesso", self.client.sent[0][1])

    def test_user_prompt_submit_non_manda_nulla(self):
        result = self.make().handle_hook(
            {"hook_event_name": "UserPromptSubmit", "cwd": "/tmp", "session_id": "s1"}
        )
        self.assertFalse(result["sent"])
        self.assertEqual(self.client.sent, [])

    def test_stop_sotto_soglia_resta_muto(self):
        d = self.make("riassunto")
        d.handle_hook(
            {"hook_event_name": "UserPromptSubmit", "cwd": "/tmp", "session_id": "s1"},
            now=1000.0,
        )
        result = d.handle_hook(
            {
                "hook_event_name": "Stop",
                "cwd": "/tmp",
                "session_id": "s1",
                "transcript_path": "/tmp/t.jsonl",
            },
            now=1010.0,
        )
        self.assertFalse(result["sent"])
        self.assertEqual(self.client.sent, [])

    def test_stop_sopra_soglia_manda_il_riassunto(self):
        d = self.make("ho finito")
        d.handle_hook(
            {"hook_event_name": "UserPromptSubmit", "cwd": "/tmp", "session_id": "s1"},
            now=1000.0,
        )
        result = d.handle_hook(
            {
                "hook_event_name": "Stop",
                "cwd": "/home/luca/Project/MayBeCompany/CRM",
                "session_id": "s1",
                "transcript_path": "/tmp/t.jsonl",
            },
            now=1200.0,
        )
        self.assertTrue(result["sent"])
        self.assertIn("ho finito", self.client.sent[0][1])
        self.assertIn("crm", self.client.sent[0][1])

    def test_stop_azzera_il_cronometro(self):
        d = self.make("x")
        d.handle_hook(
            {"hook_event_name": "UserPromptSubmit", "cwd": "/tmp", "session_id": "s1"},
            now=1000.0,
        )
        d.handle_hook(
            {"hook_event_name": "Stop", "cwd": "/tmp", "session_id": "s1"}, now=1200.0
        )
        self.assertIsNone(self.clock.elapsed("s1", now=1300.0))

    def test_evento_sconosciuto_ignorato(self):
        result = self.make().handle_hook({"hook_event_name": "PreCompact", "cwd": "/tmp"})
        self.assertFalse(result["sent"])

    def test_senza_chat_id_non_manda(self):
        d = daemon.Daemon(
            cfg={
                "bot_token": "T",
                "chat_id": None,
                "stop_threshold_seconds": 120,
                "transcript_tail_chars": 600,
            },
            client=self.client,
            clock=self.clock,
        )
        result = d.handle_hook(
            {"hook_event_name": "Notification", "cwd": "/tmp", "message": "x"}
        )
        self.assertFalse(result["sent"])
        self.assertIn("chat_id", result["reason"])


class TestHandleUpdate(DaemonCase):
    def test_scarta_chat_id_estraneo(self):
        self.make().handle_update(
            {"update_id": 1, "message": {"chat": {"id": 999}, "text": "ciao"}}
        )
        self.assertEqual(self.client.sent, [])

    def test_accetta_il_chat_id_configurato(self):
        self.make().handle_update(
            {"update_id": 1, "message": {"chat": {"id": 42}, "text": "/stato"}}
        )
        self.assertEqual(len(self.client.sent), 1)

    def test_update_senza_messaggio_non_solleva(self):
        self.make().handle_update({"update_id": 1})
        self.assertEqual(self.client.sent, [])


if __name__ == "__main__":
    unittest.main()
