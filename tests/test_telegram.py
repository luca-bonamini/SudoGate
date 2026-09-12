import io
import json
import unittest
import urllib.error

from sudogate import telegram


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class FakeOpener:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        item = self.payloads.pop(0)
        if isinstance(item, Exception):
            raise item
        return FakeResponse(json.dumps(item).encode())


class TestSendMessage(unittest.TestCase):
    def test_calls_the_right_endpoint(self):
        opener = FakeOpener([{"ok": True, "result": {"message_id": 7}}])
        client = telegram.Client("TOK", opener=opener)
        result = client.send_message(42, "ciao")
        self.assertEqual(result["message_id"], 7)
        self.assertEqual(
            opener.requests[0].full_url,
            "https://api.telegram.org/botTOK/sendMessage",
        )

    def test_sends_chat_id_and_text(self):
        opener = FakeOpener([{"ok": True, "result": {}}])
        telegram.Client("TOK", opener=opener).send_message(42, "ciao")
        body = json.loads(opener.requests[0].data.decode())
        self.assertEqual(body["chat_id"], 42)
        self.assertEqual(body["text"], "ciao")

    def test_buttons_become_inline_keyboard(self):
        opener = FakeOpener([{"ok": True, "result": {}}])
        client = telegram.Client("TOK", opener=opener)
        client.send_message(42, "x", buttons=[[("Approva", "a:1"), ("Nega", "n:1")]])
        body = json.loads(opener.requests[0].data.decode())
        keyboard = body["reply_markup"]["inline_keyboard"]
        self.assertEqual(keyboard[0][0], {"text": "Approva", "callback_data": "a:1"})
        self.assertEqual(keyboard[0][1], {"text": "Nega", "callback_data": "n:1"})

    def test_no_reply_markup_without_buttons(self):
        opener = FakeOpener([{"ok": True, "result": {}}])
        telegram.Client("TOK", opener=opener).send_message(42, "x")
        self.assertNotIn("reply_markup", json.loads(opener.requests[0].data.decode()))

    def test_callback_data_too_long(self):
        client = telegram.Client("TOK", opener=FakeOpener([]))
        with self.assertRaises(ValueError):
            client.send_message(42, "x", buttons=[[("Ok", "z" * 65)]])

    def test_response_not_ok(self):
        opener = FakeOpener([{"ok": False, "description": "chat not found"}])
        client = telegram.Client("TOK", opener=opener)
        with self.assertRaises(telegram.TelegramError) as ctx:
            client.send_message(42, "x")
        self.assertIn("chat not found", str(ctx.exception))

    def test_network_error(self):
        opener = FakeOpener([urllib.error.URLError("down")])
        client = telegram.Client("TOK", opener=opener)
        with self.assertRaises(telegram.TelegramError):
            client.send_message(42, "x")

    def test_token_absent_from_error(self):
        opener = FakeOpener([urllib.error.URLError("down")])
        client = telegram.Client("SECRET", opener=opener)
        with self.assertRaises(telegram.TelegramError) as ctx:
            client.send_message(42, "x")
        self.assertNotIn("SECRET", str(ctx.exception))


class TestGetUpdates(unittest.TestCase):
    def test_passes_offset_and_timeout(self):
        opener = FakeOpener([{"ok": True, "result": [{"update_id": 5}]}])
        updates = telegram.Client("TOK", opener=opener).get_updates(offset=3, timeout=30)
        body = json.loads(opener.requests[0].data.decode())
        self.assertEqual(body["offset"], 3)
        self.assertEqual(body["timeout"], 30)
        self.assertEqual(updates[0]["update_id"], 5)


if __name__ == "__main__":
    unittest.main()
