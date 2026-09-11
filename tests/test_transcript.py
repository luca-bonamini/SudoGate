import json
import pathlib
import tempfile
import unittest

from ctg import transcript


def assistant(text):
    return json.dumps(
        {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}
    )


def user(text):
    return json.dumps({"type": "user", "message": {"content": text}})


class TestLastAssistantText(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write(self, lines):
        path = self.dir / "t.jsonl"
        path.write_text("\n".join(lines) + "\n")
        return path

    def test_prende_lultimo_assistant(self):
        path = self.write([assistant("primo"), user("domanda"), assistant("ultimo")])
        self.assertEqual(transcript.last_assistant_text(path), "ultimo")

    def test_ignora_i_blocchi_non_testuali(self):
        path = self.write(
            [
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "content": [
                                {"type": "tool_use", "name": "Bash"},
                                {"type": "text", "text": "fatto"},
                            ]
                        },
                    }
                )
            ]
        )
        self.assertEqual(transcript.last_assistant_text(path), "fatto")

    def test_salta_le_righe_non_json(self):
        path = self.write(["{troncata", assistant("valido")])
        self.assertEqual(transcript.last_assistant_text(path), "valido")

    def test_nessun_assistant(self):
        self.assertIsNone(transcript.last_assistant_text(self.write([user("ciao")])))

    def test_file_assente(self):
        self.assertIsNone(transcript.last_assistant_text(self.dir / "manca.jsonl"))

    def test_tronca_con_ellissi(self):
        path = self.write([assistant("x" * 50)])
        result = transcript.last_assistant_text(path, max_chars=10)
        self.assertEqual(len(result), 10)
        self.assertTrue(result.endswith("…"))

    def test_sotto_soglia_non_tronca(self):
        path = self.write([assistant("breve")])
        self.assertEqual(transcript.last_assistant_text(path, max_chars=10), "breve")

    def test_assistant_vuoto_ignorato(self):
        path = self.write([assistant("vero"), assistant("   ")])
        self.assertEqual(transcript.last_assistant_text(path), "vero")


if __name__ == "__main__":
    unittest.main()
