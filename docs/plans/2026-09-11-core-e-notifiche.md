# Core e notifiche — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un daemon Telegram su `home-server` che riceve eventi dagli hook di Claude Code e manda notifiche in chat, filtrando il rumore dei turni brevi.

**Architecture:** Un processo `claude-telegram` come unit utente systemd. Gli hook di Claude Code sono un solo entrypoint Python che invia il payload al daemon su socket unix e termina. Il daemon è l'unico che contatta `api.telegram.org`. Tutta la logica testabile sta nel package `ctg/`; i file in `bin/` sono sottili.

**Tech Stack:** Python 3.14, solo standard library (`urllib`, `json`, `socket`, `subprocess`, `pathlib`, `unittest`). systemd user unit. Nessun pacchetto da installare, nessun venv.

**Spec:** `docs/2026-09-11-telegram-gate-design.md`

## Global Constraints

- Solo standard library di Python 3.14. Nessuna dipendenza esterna, nessun venv.
- Repo: `~/Project/personal/claude-telegram`. Il codice non gira dal repo: `install.sh` lo copia nelle posizioni di esecuzione.
- Configurazione e stato in `~/.claude/telegram/`, override con la variabile d'ambiente `CTG_HOME` (i test la usano sempre).
- `config.json` deve avere permessi `0600`. Il loader rifiuta permessi più larghi.
- Segreti mai nel repo, mai nei log, mai negli output dei test.
- Se `$CTG_HOME/disabled` esiste, ogni hook esce `0` immediatamente senza altri effetti.
- Hook non bloccanti: `claude-tg-hook` esce sempre `0`, anche se il daemon è fermo o il socket manca.
- Soglia notifica su `Stop`: 120 s, chiave `stop_threshold_seconds`.
- Troncamento del testo estratto dal transcript: 600 caratteri, chiave `transcript_tail_chars`.
- Ogni update Telegram con `chat_id` diverso da quello in configurazione viene scartato senza risposta.
- Messaggi di errore, log e commit in italiano. Nomi di funzioni, variabili e file in inglese.

---

### Task 1: Loader di configurazione

**Files:**
- Create: `ctg/__init__.py`
- Create: `ctg/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: niente.
- Produces: `ctg.config.home() -> pathlib.Path`, `ctg.config.load(path: pathlib.Path | None = None) -> dict`, `ctg.config.ConfigError`, `ctg.config.DEFAULTS: dict`. Il dict restituito ha almeno le chiavi `bot_token: str`, `chat_id: int | None`, `stop_threshold_seconds: int`, `transcript_tail_chars: int`, `approval_ttl_seconds: int`, `cache_ttl_seconds: int`, `totp_always: bool`, `destructive_patterns: list[str]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import json
import os
import pathlib
import tempfile
import unittest

from ctg import config


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

    def test_applica_i_default_alle_chiavi_mancanti(self):
        path = write_config(self.dir, {"bot_token": "T", "chat_id": 42})
        cfg = config.load(path)
        self.assertEqual(cfg["bot_token"], "T")
        self.assertEqual(cfg["chat_id"], 42)
        self.assertEqual(cfg["stop_threshold_seconds"], 120)
        self.assertEqual(cfg["transcript_tail_chars"], 600)
        self.assertFalse(cfg["totp_always"])
        self.assertIsInstance(cfg["destructive_patterns"], list)
        self.assertTrue(cfg["destructive_patterns"])

    def test_il_valore_esplicito_vince_sul_default(self):
        path = write_config(self.dir, {"bot_token": "T", "stop_threshold_seconds": 30})
        self.assertEqual(config.load(path)["stop_threshold_seconds"], 30)

    def test_token_mancante(self):
        path = write_config(self.dir, {"chat_id": 42})
        with self.assertRaises(config.ConfigError) as ctx:
            config.load(path)
        self.assertIn("bot_token", str(ctx.exception))

    def test_permessi_troppo_larghi(self):
        path = write_config(self.dir, {"bot_token": "T"}, mode=0o644)
        with self.assertRaises(config.ConfigError) as ctx:
            config.load(path)
        self.assertIn("0600", str(ctx.exception))

    def test_il_messaggio_di_errore_non_contiene_il_token(self):
        path = write_config(self.dir, {"bot_token": "SEGRETO", "chat_id": 1}, mode=0o644)
        with self.assertRaises(config.ConfigError) as ctx:
            config.load(path)
        self.assertNotIn("SEGRETO", str(ctx.exception))

    def test_file_assente(self):
        with self.assertRaises(config.ConfigError):
            config.load(pathlib.Path(self.dir) / "non-esiste.json")

    def test_json_malformato(self):
        path = pathlib.Path(self.dir) / "config.json"
        path.write_text("{non json")
        path.chmod(0o600)
        with self.assertRaises(config.ConfigError):
            config.load(path)


class TestHome(unittest.TestCase):
    def test_ctg_home_ha_la_precedenza(self):
        os.environ["CTG_HOME"] = "/tmp/ctg-test-home"
        self.addCleanup(os.environ.pop, "CTG_HOME", None)
        self.assertEqual(config.home(), pathlib.Path("/tmp/ctg-test-home"))

    def test_default_sotto_claude(self):
        os.environ.pop("CTG_HOME", None)
        self.assertEqual(config.home(), pathlib.Path.home() / ".claude" / "telegram")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Project/personal/claude-telegram && python3 -m unittest tests.test_config -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'ctg'`

- [ ] **Step 3: Write minimal implementation**

```python
# ctg/__init__.py
"""Layer Telegram per Claude Code su home-server."""
```

```python
# ctg/config.py
import json
import os
import pathlib

DEFAULTS = {
    "chat_id": None,
    "stop_threshold_seconds": 120,
    "transcript_tail_chars": 600,
    "approval_ttl_seconds": 120,
    "cache_ttl_seconds": 28800,
    "totp_always": False,
    "destructive_patterns": [
        r"\brm\s+(-\w+\s+)*-\w*r\w*f",
        r"\bdd\b",
        r"\bmkfs\b",
        r"\b(fdisk|parted)\b",
        r"\b(shutdown|reboot|poweroff|halt)\b",
        r"\b(passwd|usermod|useradd|userdel)\b",
        r"\b(visudo|sudoers)\b",
        r"/etc/netplan",
        r"\b(chown|chmod)\b.*\s-\w*R",
        r"\b(iptables|ufw|nft)\b",
        r"\bsystemctl\s+(disable|mask)\b",
        r"\bapt(-get)?\s+(remove|purge|autoremove)\b",
        r"\|\s*(ba)?sh\b",
        r">\s*/dev/(sd|nvme|vd)",
        r"\btailscale\s+down\b",
    ],
}


class ConfigError(Exception):
    """Configurazione assente, illeggibile o con permessi sbagliati."""


def home():
    override = os.environ.get("CTG_HOME")
    if override:
        return pathlib.Path(override)
    return pathlib.Path.home() / ".claude" / "telegram"


def config_path():
    return home() / "config.json"


def load(path=None):
    path = pathlib.Path(path) if path is not None else config_path()
    try:
        mode = path.stat().st_mode & 0o777
    except OSError as exc:
        raise ConfigError(f"configurazione non leggibile: {path}") from exc
    if mode & 0o077:
        raise ConfigError(
            f"permessi {mode:04o} troppo larghi su {path}, attesi 0600"
        )
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ConfigError(f"configurazione illeggibile: {path}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"la configurazione in {path} non è un oggetto JSON")
    if not raw.get("bot_token"):
        raise ConfigError(f"bot_token mancante in {path}")
    cfg = dict(DEFAULTS)
    cfg.update(raw)
    return cfg
```

Il controllo dei permessi precede la lettura, così un file con permessi larghi viene rifiutato prima che il token entri in memoria. `ConfigError` riporta il path e mai il contenuto.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Project/personal/claude-telegram && python3 -m unittest tests.test_config -v`
Expected: PASS, 9 test

- [ ] **Step 5: Commit**

```bash
cd ~/Project/personal/claude-telegram
git add ctg/__init__.py ctg/config.py tests/test_config.py
git commit -m "feat: loader di configurazione con controllo dei permessi"
```

---

### Task 2: Client Telegram

**Files:**
- Create: `ctg/telegram.py`
- Test: `tests/test_telegram.py`

**Interfaces:**
- Consumes: niente.
- Produces: `ctg.telegram.Client(token: str, opener=None, timeout: int = 35)` con i metodi `send_message(chat_id: int, text: str, buttons: list[list[tuple[str, str]]] | None = None) -> dict` e `get_updates(offset: int, timeout: int = 30) -> list[dict]`; `ctg.telegram.TelegramError`. `buttons` è una lista di righe, ogni riga una lista di coppie `(etichetta, callback_data)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_telegram.py
import io
import json
import unittest
import urllib.error

from ctg import telegram


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
    def test_chiama_lendpoint_giusto(self):
        opener = FakeOpener([{"ok": True, "result": {"message_id": 7}}])
        client = telegram.Client("TOK", opener=opener)
        result = client.send_message(42, "ciao")
        self.assertEqual(result["message_id"], 7)
        self.assertEqual(
            opener.requests[0].full_url,
            "https://api.telegram.org/botTOK/sendMessage",
        )

    def test_manda_chat_id_e_testo(self):
        opener = FakeOpener([{"ok": True, "result": {}}])
        telegram.Client("TOK", opener=opener).send_message(42, "ciao")
        body = json.loads(opener.requests[0].data.decode())
        self.assertEqual(body["chat_id"], 42)
        self.assertEqual(body["text"], "ciao")

    def test_i_bottoni_diventano_inline_keyboard(self):
        opener = FakeOpener([{"ok": True, "result": {}}])
        client = telegram.Client("TOK", opener=opener)
        client.send_message(42, "x", buttons=[[("Approva", "a:1"), ("Nega", "n:1")]])
        body = json.loads(opener.requests[0].data.decode())
        keyboard = body["reply_markup"]["inline_keyboard"]
        self.assertEqual(keyboard[0][0], {"text": "Approva", "callback_data": "a:1"})
        self.assertEqual(keyboard[0][1], {"text": "Nega", "callback_data": "n:1"})

    def test_senza_bottoni_non_manda_reply_markup(self):
        opener = FakeOpener([{"ok": True, "result": {}}])
        telegram.Client("TOK", opener=opener).send_message(42, "x")
        self.assertNotIn("reply_markup", json.loads(opener.requests[0].data.decode()))

    def test_callback_data_troppo_lungo(self):
        client = telegram.Client("TOK", opener=FakeOpener([]))
        with self.assertRaises(ValueError):
            client.send_message(42, "x", buttons=[[("Ok", "z" * 65)]])

    def test_risposta_non_ok(self):
        opener = FakeOpener([{"ok": False, "description": "chat not found"}])
        client = telegram.Client("TOK", opener=opener)
        with self.assertRaises(telegram.TelegramError) as ctx:
            client.send_message(42, "x")
        self.assertIn("chat not found", str(ctx.exception))

    def test_errore_di_rete(self):
        opener = FakeOpener([urllib.error.URLError("giù")])
        client = telegram.Client("TOK", opener=opener)
        with self.assertRaises(telegram.TelegramError):
            client.send_message(42, "x")

    def test_il_token_non_compare_nellerrore(self):
        opener = FakeOpener([urllib.error.URLError("giù")])
        client = telegram.Client("SEGRETO", opener=opener)
        with self.assertRaises(telegram.TelegramError) as ctx:
            client.send_message(42, "x")
        self.assertNotIn("SEGRETO", str(ctx.exception))


class TestGetUpdates(unittest.TestCase):
    def test_passa_offset_e_timeout(self):
        opener = FakeOpener([{"ok": True, "result": [{"update_id": 5}]}])
        updates = telegram.Client("TOK", opener=opener).get_updates(offset=3, timeout=30)
        body = json.loads(opener.requests[0].data.decode())
        self.assertEqual(body["offset"], 3)
        self.assertEqual(body["timeout"], 30)
        self.assertEqual(updates[0]["update_id"], 5)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Project/personal/claude-telegram && python3 -m unittest tests.test_telegram -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'ctg.telegram'`

- [ ] **Step 3: Write minimal implementation**

```python
# ctg/telegram.py
import json
import urllib.error
import urllib.request

API_BASE = "https://api.telegram.org"
CALLBACK_DATA_MAX = 64


class TelegramError(Exception):
    """L'API Telegram ha rifiutato la chiamata o è irraggiungibile."""


class Client:
    def __init__(self, token, opener=None, timeout=35):
        self._token = token
        self._opener = opener or urllib.request.build_opener()
        self._timeout = timeout

    def send_message(self, chat_id, text, buttons=None):
        params = {"chat_id": chat_id, "text": text}
        if buttons:
            params["reply_markup"] = {"inline_keyboard": _keyboard(buttons)}
        return self._call("sendMessage", params)

    def get_updates(self, offset, timeout=30):
        return self._call(
            "getUpdates",
            {"offset": offset, "timeout": timeout},
            http_timeout=timeout + 5,
        )

    def _call(self, method, params, http_timeout=None):
        url = f"{API_BASE}/bot{self._token}/{method}"
        request = urllib.request.Request(
            url,
            data=json.dumps(params).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with self._opener.open(
                request, timeout=http_timeout or self._timeout
            ) as response:
                body = json.loads(response.read().decode())
        except urllib.error.URLError as exc:
            raise TelegramError(f"{method} non raggiungibile: {exc.reason}") from None
        except (OSError, ValueError) as exc:
            raise TelegramError(f"{method} ha dato una risposta illeggibile") from None
        if not body.get("ok"):
            raise TelegramError(f"{method}: {body.get('description', 'risposta non ok')}")
        return body["result"]


def _keyboard(rows):
    keyboard = []
    for row in rows:
        cells = []
        for label, data in row:
            encoded = data.encode()
            if len(encoded) > CALLBACK_DATA_MAX:
                raise ValueError(
                    f"callback_data di {len(encoded)} byte, il massimo è {CALLBACK_DATA_MAX}"
                )
            cells.append({"text": label, "callback_data": data})
        keyboard.append(cells)
    return keyboard
```

`raise ... from None` sopprime la catena di eccezioni: l'URL originale contiene il token e comparirebbe nel traceback.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Project/personal/claude-telegram && python3 -m unittest tests.test_telegram -v`
Expected: PASS, 9 test

- [ ] **Step 5: Commit**

```bash
cd ~/Project/personal/claude-telegram
git add ctg/telegram.py tests/test_telegram.py
git commit -m "feat: client Telegram su urllib, senza token nei messaggi di errore"
```

---

### Task 3: Etichetta di progetto dalla directory

**Files:**
- Create: `ctg/sessions.py`
- Test: `tests/test_sessions.py`

**Interfaces:**
- Consumes: niente.
- Produces: `ctg.sessions.tmux_sessions(runner=None) -> dict[str, str]` che mappa nome sessione a directory; `ctg.sessions.label_for_cwd(cwd: str, sessions: dict[str, str]) -> str`. `runner` ha la firma di `subprocess.run`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sessions.py
import subprocess
import unittest

from ctg import sessions


def fake_runner(stdout, returncode=0):
    def run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr="")

    return run


TMUX = {
    "rc-maybecompany": "/home/luca/Project/MayBeCompany",
    "rc-crm": "/home/luca/Project/MayBeCompany/CRM",
    "rc-personal": "/home/luca/Project/personal",
}


class TestTmuxSessions(unittest.TestCase):
    def test_legge_nome_e_directory(self):
        runner = fake_runner(
            "rc-crm\t/home/luca/Project/MayBeCompany/CRM\n"
            "rc-personal\t/home/luca/Project/personal\n"
        )
        self.assertEqual(
            sessions.tmux_sessions(runner),
            {
                "rc-crm": "/home/luca/Project/MayBeCompany/CRM",
                "rc-personal": "/home/luca/Project/personal",
            },
        )

    def test_tmux_assente_o_senza_server(self):
        self.assertEqual(sessions.tmux_sessions(fake_runner("", returncode=1)), {})

    def test_riga_malformata_ignorata(self):
        runner = fake_runner("senza-tab\nrc-crm\t/tmp/crm\n")
        self.assertEqual(sessions.tmux_sessions(runner), {"rc-crm": "/tmp/crm"})


class TestLabelForCwd(unittest.TestCase):
    def test_match_esatto(self):
        self.assertEqual(
            sessions.label_for_cwd("/home/luca/Project/MayBeCompany", TMUX),
            "maybecompany",
        )

    def test_sottodirectory(self):
        self.assertEqual(
            sessions.label_for_cwd("/home/luca/Project/personal/claude-telegram", TMUX),
            "personal",
        )

    def test_vince_il_prefisso_piu_lungo(self):
        self.assertEqual(
            sessions.label_for_cwd("/home/luca/Project/MayBeCompany/CRM/src", TMUX),
            "crm",
        )

    def test_nessuna_sessione_usa_il_basename(self):
        self.assertEqual(sessions.label_for_cwd("/srv/qualcosa", TMUX), "qualcosa")

    def test_senza_tmux_usa_il_basename(self):
        self.assertEqual(sessions.label_for_cwd("/home/luca/Project/personal", {}), "personal")

    def test_non_confonde_prefissi_parziali(self):
        tmux = {"rc-papayamarket": "/home/luca/Project/MayBeCompany/papaya"}
        self.assertEqual(
            sessions.label_for_cwd("/home/luca/Project/MayBeCompany/papayaShopper", tmux),
            "papayaShopper",
        )


if __name__ == "__main__":
    unittest.main()
```

`test_non_confonde_prefissi_parziali` è il caso che un confronto con `startswith` nudo sbaglia: `/…/papayaShopper` inizia con `/…/papaya` ma non è dentro quella directory.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Project/personal/claude-telegram && python3 -m unittest tests.test_sessions -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'ctg.sessions'`

- [ ] **Step 3: Write minimal implementation**

```python
# ctg/sessions.py
import pathlib
import subprocess

LIST_FORMAT = "#{session_name}\t#{session_path}"


def tmux_sessions(runner=None):
    runner = runner or subprocess.run
    try:
        completed = runner(
            ["tmux", "list-sessions", "-F", LIST_FORMAT],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if completed.returncode != 0:
        return {}
    found = {}
    for line in (completed.stdout or "").splitlines():
        if "\t" not in line:
            continue
        name, path = line.split("\t", 1)
        if name and path:
            found[name] = path
    return found


def label_for_cwd(cwd, sessions):
    current = pathlib.PurePosixPath(cwd)
    best_name = None
    best_len = -1
    for name, path in sessions.items():
        candidate = pathlib.PurePosixPath(path)
        if current == candidate or candidate in current.parents:
            if len(str(candidate)) > best_len:
                best_name, best_len = name, len(str(candidate))
    if best_name:
        return best_name.removeprefix("rc-")
    return current.name
```

`candidate in current.parents` confronta componente per componente, quindi `papaya` non risulta genitore di `papayaShopper`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Project/personal/claude-telegram && python3 -m unittest tests.test_sessions -v`
Expected: PASS, 9 test

- [ ] **Step 5: Commit**

```bash
cd ~/Project/personal/claude-telegram
git add ctg/sessions.py tests/test_sessions.py
git commit -m "feat: etichetta di progetto dal cwd, via sessioni tmux"
```

---

### Task 4: Estrazione dell'ultimo messaggio dal transcript

**Files:**
- Create: `ctg/transcript.py`
- Test: `tests/test_transcript.py`

**Interfaces:**
- Consumes: niente.
- Produces: `ctg.transcript.last_assistant_text(path, max_chars: int = 600, tail_bytes: int = 262144) -> str | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_transcript.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Project/personal/claude-telegram && python3 -m unittest tests.test_transcript -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'ctg.transcript'`

- [ ] **Step 3: Write minimal implementation**

```python
# ctg/transcript.py
import json
import pathlib

DEFAULT_TAIL_BYTES = 262144


def last_assistant_text(path, max_chars=600, tail_bytes=DEFAULT_TAIL_BYTES):
    data = _read_tail(pathlib.Path(path), tail_bytes)
    if data is None:
        return None
    found = None
    for line in data.splitlines():
        text = _assistant_text(line)
        if text:
            found = text
    if found is None:
        return None
    if len(found) <= max_chars:
        return found
    return found[: max_chars - 1].rstrip() + "…"


def _read_tail(path, tail_bytes):
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - tail_bytes))
            raw = handle.read()
    except OSError:
        return None
    return raw.decode("utf-8", errors="replace")


def _assistant_text(line):
    try:
        record = json.loads(line)
    except ValueError:
        return None
    if not isinstance(record, dict) or record.get("type") != "assistant":
        return None
    content = (record.get("message") or {}).get("content")
    if not isinstance(content, list):
        return None
    parts = [
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    joined = "\n".join(part for part in parts if part).strip()
    return joined or None
```

La lettura parte dagli ultimi 256 KB perché un transcript di una sessione lunga arriva a decine di megabyte. La prima riga del blocco può risultare tagliata a metà: `_assistant_text` la scarta come JSON non valido.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Project/personal/claude-telegram && python3 -m unittest tests.test_transcript -v`
Expected: PASS, 8 test

- [ ] **Step 5: Commit**

```bash
cd ~/Project/personal/claude-telegram
git add ctg/transcript.py tests/test_transcript.py
git commit -m "feat: estrazione dell'ultimo messaggio assistant dal transcript"
```

---

### Task 5: Filtro anti-rumore su Stop

**Files:**
- Create: `ctg/turns.py`
- Test: `tests/test_turns.py`

**Interfaces:**
- Consumes: niente.
- Produces: `ctg.turns.TurnClock(path)` con `mark_prompt(session_id: str, now: float) -> None`, `elapsed(session_id: str, now: float) -> float | None` e `clear(session_id: str) -> None`; `ctg.turns.should_notify_stop(elapsed: float | None, threshold: float, from_telegram: bool) -> bool`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_turns.py
import pathlib
import tempfile
import unittest

from ctg import turns


class TestShouldNotifyStop(unittest.TestCase):
    def test_turno_breve_resta_muto(self):
        self.assertFalse(turns.should_notify_stop(10.0, 120, from_telegram=False))

    def test_turno_lungo_notifica(self):
        self.assertTrue(turns.should_notify_stop(130.0, 120, from_telegram=False))

    def test_esattamente_la_soglia_notifica(self):
        self.assertTrue(turns.should_notify_stop(120.0, 120, from_telegram=False))

    def test_da_telegram_notifica_sempre(self):
        self.assertTrue(turns.should_notify_stop(1.0, 120, from_telegram=True))

    def test_senza_t0_e_senza_telegram_resta_muto(self):
        self.assertFalse(turns.should_notify_stop(None, 120, from_telegram=False))

    def test_senza_t0_ma_da_telegram_notifica(self):
        self.assertTrue(turns.should_notify_stop(None, 120, from_telegram=True))


class TestTurnClock(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self._tmp.name) / "turns.json"
        self.addCleanup(self._tmp.cleanup)

    def test_elapsed_dopo_mark(self):
        clock = turns.TurnClock(self.path)
        clock.mark_prompt("s1", now=1000.0)
        self.assertEqual(clock.elapsed("s1", now=1130.0), 130.0)

    def test_sessione_sconosciuta(self):
        self.assertIsNone(turns.TurnClock(self.path).elapsed("ignota", now=1.0))

    def test_lo_stato_sopravvive_a_una_nuova_istanza(self):
        turns.TurnClock(self.path).mark_prompt("s1", now=1000.0)
        self.assertEqual(turns.TurnClock(self.path).elapsed("s1", now=1005.0), 5.0)

    def test_sessioni_indipendenti(self):
        clock = turns.TurnClock(self.path)
        clock.mark_prompt("s1", now=1000.0)
        clock.mark_prompt("s2", now=1100.0)
        self.assertEqual(clock.elapsed("s1", now=1200.0), 200.0)
        self.assertEqual(clock.elapsed("s2", now=1200.0), 100.0)

    def test_clear_dimentica_la_sessione(self):
        clock = turns.TurnClock(self.path)
        clock.mark_prompt("s1", now=1000.0)
        clock.clear("s1")
        self.assertIsNone(clock.elapsed("s1", now=1200.0))

    def test_file_corrotto_non_solleva(self):
        self.path.write_text("{rotto")
        clock = turns.TurnClock(self.path)
        self.assertIsNone(clock.elapsed("s1", now=1.0))
        clock.mark_prompt("s1", now=1.0)
        self.assertEqual(clock.elapsed("s1", now=2.0), 1.0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Project/personal/claude-telegram && python3 -m unittest tests.test_turns -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'ctg.turns'`

- [ ] **Step 3: Write minimal implementation**

```python
# ctg/turns.py
import json
import os
import pathlib


def should_notify_stop(elapsed, threshold, from_telegram):
    if from_telegram:
        return True
    return elapsed is not None and elapsed >= threshold


class TurnClock:
    """Istante dell'ultimo prompt utente, per sessione, su file."""

    def __init__(self, path):
        self._path = pathlib.Path(path)

    def mark_prompt(self, session_id, now):
        data = self._read()
        data[session_id] = now
        self._write(data)

    def elapsed(self, session_id, now):
        started = self._read().get(session_id)
        if started is None:
            return None
        return now - started

    def clear(self, session_id):
        data = self._read()
        if data.pop(session_id, None) is not None:
            self._write(data)

    def _read(self):
        try:
            data = json.loads(self._path.read_text())
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, data):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        os.replace(tmp, self._path)
```

La scrittura passa da un file temporaneo più `os.replace`, che è atomico sullo stesso filesystem: cinque sessioni possono marcare un prompt nello stesso momento senza lasciare il file a metà.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Project/personal/claude-telegram && python3 -m unittest tests.test_turns -v`
Expected: PASS, 12 test

- [ ] **Step 5: Commit**

```bash
cd ~/Project/personal/claude-telegram
git add ctg/turns.py tests/test_turns.py
git commit -m "feat: filtro anti-rumore su Stop con durata del turno per sessione"
```

---

### Task 6: Canale IPC su socket unix

**Files:**
- Create: `ctg/ipc.py`
- Test: `tests/test_ipc.py`

**Interfaces:**
- Consumes: niente.
- Produces: `ctg.ipc.request(sock_path, payload: dict, timeout: float) -> dict`, `ctg.ipc.serve(sock_path, handler, stop_event)` dove `handler(payload: dict) -> dict`; `ctg.ipc.IPCError`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ipc.py
import pathlib
import tempfile
import threading
import unittest

from ctg import ipc


class TestIPC(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.sock = pathlib.Path(self._tmp.name) / "sock"
        self.stop = threading.Event()
        self.addCleanup(self._tmp.cleanup)

    def start(self, handler):
        ready = threading.Event()

        def run():
            ipc.serve(self.sock, handler, self.stop, on_ready=ready.set)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.assertTrue(ready.wait(5), "il server non si è messo in ascolto")
        self.addCleanup(thread.join, 5)
        self.addCleanup(self.stop.set)
        return thread

    def test_andata_e_ritorno(self):
        self.start(lambda payload: {"echo": payload["valore"]})
        self.assertEqual(
            ipc.request(self.sock, {"valore": 7}, timeout=5), {"echo": 7}
        )

    def test_richieste_in_sequenza(self):
        self.start(lambda payload: {"n": payload["n"] * 2})
        for n in range(5):
            self.assertEqual(ipc.request(self.sock, {"n": n}, timeout=5), {"n": n * 2})

    def test_il_socket_ha_permessi_0600(self):
        self.start(lambda payload: {})
        self.assertEqual(self.sock.stat().st_mode & 0o777, 0o600)

    def test_socket_assente(self):
        with self.assertRaises(ipc.IPCError):
            ipc.request(self.sock, {"x": 1}, timeout=1)

    def test_handler_che_solleva_non_uccide_il_server(self):
        def handler(payload):
            if payload.get("boom"):
                raise RuntimeError("scoppio")
            return {"ok": True}

        self.start(handler)
        with self.assertRaises(ipc.IPCError):
            ipc.request(self.sock, {"boom": True}, timeout=5)
        self.assertEqual(ipc.request(self.sock, {}, timeout=5), {"ok": True})

    def test_timeout_del_client(self):
        import time

        self.start(lambda payload: (time.sleep(3), {"tardi": True})[1])
        with self.assertRaises(ipc.IPCError):
            ipc.request(self.sock, {}, timeout=0.5)

    def test_socket_stantio_viene_rimpiazzato(self):
        self.sock.write_text("non un socket")
        self.start(lambda payload: {"ok": True})
        self.assertEqual(ipc.request(self.sock, {}, timeout=5), {"ok": True})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Project/personal/claude-telegram && python3 -m unittest tests.test_ipc -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'ctg.ipc'`

- [ ] **Step 3: Write minimal implementation**

```python
# ctg/ipc.py
import json
import os
import pathlib
import socket

ACCEPT_POLL_SECONDS = 0.5


class IPCError(Exception):
    """Il daemon non risponde, o ha risposto in modo illeggibile."""


def request(sock_path, payload, timeout):
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout)
    try:
        client.connect(str(sock_path))
        client.sendall((json.dumps(payload) + "\n").encode())
        return json.loads(_read_line(client))
    except (OSError, ValueError) as exc:
        raise IPCError(f"richiesta al daemon fallita: {exc}") from None
    finally:
        client.close()


def serve(sock_path, handler, stop_event, on_ready=None):
    path = pathlib.Path(sock_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(str(path))
        os.chmod(path, 0o600)
        server.listen(16)
        server.settimeout(ACCEPT_POLL_SECONDS)
        if on_ready:
            on_ready()
        while not stop_event.is_set():
            try:
                conn, _ = server.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            with conn:
                _handle(conn, handler)
    finally:
        server.close()
        if path.exists():
            path.unlink()


def _handle(conn, handler):
    conn.settimeout(130)
    try:
        payload = json.loads(_read_line(conn))
    except (OSError, ValueError):
        return
    try:
        reply = handler(payload)
    except Exception as exc:  # noqa: BLE001 - un handler rotto non deve fermare il server
        reply = {"error": str(exc)}
    try:
        conn.sendall((json.dumps(reply) + "\n").encode())
    except OSError:
        pass


def _read_line(sock):
    buffer = b""
    while not buffer.endswith(b"\n"):
        chunk = sock.recv(4096)
        if not chunk:
            raise OSError("connessione chiusa prima della fine della risposta")
        buffer += chunk
        if len(buffer) > 1_048_576:
            raise OSError("risposta oltre 1 MB")
    return buffer.decode()
```

`accept` ha un timeout di mezzo secondo invece di bloccare, così `stop_event` viene controllato e il daemon si ferma senza dover ricevere una connessione finta. Il socket stantio lasciato da un daemon ucciso viene rimosso al bind, non riusato. Il timeout di 130 s lato connessione lascia spazio all'attesa di 120 s del gate, che arriva nel piano 3.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Project/personal/claude-telegram && python3 -m unittest tests.test_ipc -v`
Expected: PASS, 7 test

- [ ] **Step 5: Commit**

```bash
cd ~/Project/personal/claude-telegram
git add ctg/ipc.py tests/test_ipc.py
git commit -m "feat: canale IPC su socket unix con permessi 0600"
```

---

### Task 7: Composizione dei messaggi di notifica

**Files:**
- Create: `ctg/messages.py`
- Test: `tests/test_messages.py`

**Interfaces:**
- Consumes: niente.
- Produces: `ctg.messages.notification(label: str, text: str) -> str`, `ctg.messages.stop(label: str, summary: str | None) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_messages.py
import unittest

from ctg import messages


class TestNotification(unittest.TestCase):
    def test_contiene_etichetta_e_testo(self):
        out = messages.notification("crm", "Claude ha bisogno del permesso di eseguire ls")
        self.assertIn("crm", out)
        self.assertIn("permesso", out)

    def test_etichetta_in_prima_riga(self):
        out = messages.notification("crm", "qualcosa")
        self.assertIn("crm", out.splitlines()[0])


class TestStop(unittest.TestCase):
    def test_con_riassunto(self):
        out = messages.stop("papayamarket", "Ho finito la migrazione")
        self.assertIn("papayamarket", out)
        self.assertIn("Ho finito la migrazione", out)

    def test_senza_riassunto(self):
        out = messages.stop("papayamarket", None)
        self.assertIn("papayamarket", out)
        self.assertTrue(out.strip())

    def test_riassunto_vuoto_trattato_come_assente(self):
        self.assertEqual(messages.stop("x", "   "), messages.stop("x", None))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Project/personal/claude-telegram && python3 -m unittest tests.test_messages -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'ctg.messages'`

- [ ] **Step 3: Write minimal implementation**

```python
# ctg/messages.py


def notification(label, text):
    return f"[{label}] permesso richiesto\n\n{text}"


def stop(label, summary):
    if summary and summary.strip():
        return f"[{label}] finito\n\n{summary.strip()}"
    return f"[{label}] finito"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Project/personal/claude-telegram && python3 -m unittest tests.test_messages -v`
Expected: PASS, 5 test

- [ ] **Step 5: Commit**

```bash
cd ~/Project/personal/claude-telegram
git add ctg/messages.py tests/test_messages.py
git commit -m "feat: composizione dei messaggi di notifica"
```

---

### Task 8: Router del daemon

**Files:**
- Create: `ctg/daemon.py`
- Test: `tests/test_daemon.py`

**Interfaces:**
- Consumes: `ctg.config.load`, `ctg.telegram.Client`, `ctg.sessions.tmux_sessions`, `ctg.sessions.label_for_cwd`, `ctg.transcript.last_assistant_text`, `ctg.turns.TurnClock`, `ctg.turns.should_notify_stop`, `ctg.messages.notification`, `ctg.messages.stop`, `ctg.ipc.serve`.
- Produces: `ctg.daemon.Daemon(cfg: dict, client, clock, sessions_reader=None, transcript_reader=None)` con `handle_hook(payload: dict) -> dict` e `handle_update(update: dict) -> None`; `ctg.daemon.main(argv=None) -> int`. `handle_hook` accetta il payload dell'hook Claude Code più la chiave `hook_event_name` e restituisce `{"sent": bool, "reason": str}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_daemon.py
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
            cfg={"bot_token": "T", "chat_id": None, "stop_threshold_seconds": 120,
                 "transcript_tail_chars": 600},
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Project/personal/claude-telegram && python3 -m unittest tests.test_daemon -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'ctg.daemon'`

- [ ] **Step 3: Write minimal implementation**

```python
# ctg/daemon.py
import signal
import threading
import time

from ctg import config, ipc, messages, sessions, telegram, transcript, turns

POLL_TIMEOUT_SECONDS = 30


class Daemon:
    def __init__(self, cfg, client, clock, sessions_reader=None, transcript_reader=None):
        self._cfg = cfg
        self._client = client
        self._clock = clock
        self._sessions_reader = sessions_reader or sessions.tmux_sessions
        self._transcript_reader = transcript_reader or (
            lambda path, max_chars: transcript.last_assistant_text(path, max_chars=max_chars)
        )
        self.started_at = time.time()

    def handle_hook(self, payload, now=None):
        now = time.time() if now is None else now
        event = payload.get("hook_event_name")
        if event == "UserPromptSubmit":
            session_id = payload.get("session_id")
            if session_id:
                self._clock.mark_prompt(session_id, now)
            return {"sent": False, "reason": "t0 registrato"}
        if event == "Notification":
            return self._send(
                messages.notification(self._label(payload), payload.get("message", ""))
            )
        if event == "Stop":
            return self._handle_stop(payload, now)
        return {"sent": False, "reason": f"evento ignorato: {event}"}

    def handle_update(self, update):
        message = update.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        if chat_id is None or chat_id != self._cfg.get("chat_id"):
            return
        text = (message.get("text") or "").strip()
        if not text:
            return
        self._send(self._reply_to(text))

    def _reply_to(self, text):
        if text.startswith("/stato"):
            uptime = int(time.time() - self.started_at)
            live = ", ".join(sorted(self._sessions_reader())) or "nessuna"
            return f"daemon attivo da {uptime}s\nsessioni tmux: {live}"
        return "comando non riconosciuto. Disponibile: /stato"

    def _handle_stop(self, payload, now):
        session_id = payload.get("session_id")
        elapsed = self._clock.elapsed(session_id, now) if session_id else None
        if session_id:
            self._clock.clear(session_id)
        if not turns.should_notify_stop(
            elapsed, self._cfg["stop_threshold_seconds"], from_telegram=False
        ):
            return {"sent": False, "reason": "turno sotto soglia"}
        summary = None
        path = payload.get("transcript_path")
        if path:
            summary = self._transcript_reader(path, self._cfg["transcript_tail_chars"])
        return self._send(messages.stop(self._label(payload), summary))

    def _label(self, payload):
        return sessions.label_for_cwd(
            payload.get("cwd", ""), self._sessions_reader()
        )

    def _send(self, text):
        chat_id = self._cfg.get("chat_id")
        if chat_id is None:
            return {"sent": False, "reason": "chat_id non configurato"}
        try:
            self._client.send_message(chat_id, text)
        except telegram.TelegramError as exc:
            return {"sent": False, "reason": str(exc)}
        return {"sent": True, "reason": "inviato"}


def main(argv=None):
    cfg = config.load()
    client = telegram.Client(cfg["bot_token"])
    clock = turns.TurnClock(config.home() / "turns.json")
    daemon = Daemon(cfg, client, clock)
    stop_event = threading.Event()

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop_event.set())

    server = threading.Thread(
        target=ipc.serve,
        args=(config.home() / "sock", daemon.handle_hook, stop_event),
        daemon=True,
    )
    server.start()

    offset = 0
    while not stop_event.is_set():
        try:
            updates = client.get_updates(offset, timeout=POLL_TIMEOUT_SECONDS)
        except telegram.TelegramError:
            stop_event.wait(5)
            continue
        for update in updates:
            offset = update["update_id"] + 1
            daemon.handle_update(update)
    server.join(5)
    return 0
```

`handle_hook` è passata direttamente a `ipc.serve` come handler: il payload che arriva dal socket è il payload dell'hook.

Il ciclo `get_updates` non rilancia in caso di errore di rete: aspetta 5 secondi e riprova, così una disconnessione passeggera non fa cadere l'unit.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Project/personal/claude-telegram && python3 -m unittest tests.test_daemon -v`
Expected: PASS, 10 test

- [ ] **Step 5: Commit**

```bash
cd ~/Project/personal/claude-telegram
git add ctg/daemon.py tests/test_daemon.py
git commit -m "feat: router del daemon per hook e update Telegram"
```

---

### Task 9: Entrypoint degli hook

**Files:**
- Create: `bin/claude-tg-hook`
- Create: `bin/claude-telegram`
- Test: `tests/test_hook_entrypoint.py`

**Interfaces:**
- Consumes: `ctg.config.home`, `ctg.ipc.request`.
- Produces: gli eseguibili `bin/claude-tg-hook` e `bin/claude-telegram`. `claude-tg-hook` legge il payload JSON dell'hook su stdin, lo inoltra al daemon e esce sempre `0`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hook_entrypoint.py
import json
import os
import pathlib
import subprocess
import tempfile
import threading
import unittest

from ctg import ipc

REPO = pathlib.Path(__file__).resolve().parent.parent
HOOK = REPO / "bin" / "claude-tg-hook"


def run_hook(payload, ctg_home, timeout=10):
    env = dict(os.environ, CTG_HOME=str(ctg_home), PYTHONPATH=str(REPO))
    return subprocess.run(
        [str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )


class TestHookEntrypoint(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.received = []
        self.stop = threading.Event()

    def start_daemon(self):
        ready = threading.Event()

        def handler(payload):
            self.received.append(payload)
            return {"sent": True, "reason": "inviato"}

        thread = threading.Thread(
            target=ipc.serve,
            args=(self.home / "sock", handler, self.stop),
            kwargs={"on_ready": ready.set},
            daemon=True,
        )
        thread.start()
        self.assertTrue(ready.wait(5))
        self.addCleanup(thread.join, 5)
        self.addCleanup(self.stop.set)

    def test_inoltra_il_payload_al_daemon(self):
        self.start_daemon()
        result = run_hook({"hook_event_name": "Notification", "message": "x"}, self.home)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.received[0]["hook_event_name"], "Notification")

    def test_esce_zero_senza_daemon(self):
        result = run_hook({"hook_event_name": "Stop"}, self.home)
        self.assertEqual(result.returncode, 0)

    def test_non_scrive_su_stdout_senza_daemon(self):
        result = run_hook({"hook_event_name": "Stop"}, self.home)
        self.assertEqual(result.stdout, "")

    def test_kill_switch(self):
        self.start_daemon()
        (self.home / "disabled").touch()
        result = run_hook({"hook_event_name": "Notification", "message": "x"}, self.home)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.received, [])

    def test_stdin_non_json(self):
        self.start_daemon()
        env = dict(os.environ, CTG_HOME=str(self.home), PYTHONPATH=str(REPO))
        result = subprocess.run(
            [str(HOOK)], input="{rotto", capture_output=True, text=True, env=env, timeout=10
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.received, [])

    def test_stdin_vuoto(self):
        self.start_daemon()
        result = subprocess.run(
            [str(HOOK)],
            input="",
            capture_output=True,
            text=True,
            env=dict(os.environ, CTG_HOME=str(self.home), PYTHONPATH=str(REPO)),
            timeout=10,
        )
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Project/personal/claude-telegram && python3 -m unittest tests.test_hook_entrypoint -v`
Expected: FAIL con `FileNotFoundError` su `bin/claude-tg-hook`

- [ ] **Step 3: Write minimal implementation**

```python
#!/usr/bin/env python3
# bin/claude-tg-hook
"""Hook di Claude Code: inoltra il payload al daemon Telegram.

Esce sempre 0. Una notifica persa non deve bloccare la sessione.
"""
import json
import os
import pathlib
import sys

REPO_LIB = pathlib.Path("/home/luca/.local/lib/claude-telegram")
if REPO_LIB.is_dir():
    sys.path.insert(0, str(REPO_LIB))

IPC_TIMEOUT_SECONDS = 1.5


def main():
    home = pathlib.Path(os.environ.get("CTG_HOME") or pathlib.Path.home() / ".claude" / "telegram")
    if (home / "disabled").exists():
        return 0
    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    try:
        payload = json.loads(raw)
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0
    try:
        from ctg import ipc

        ipc.request(home / "sock", payload, timeout=IPC_TIMEOUT_SECONDS)
    except Exception:  # noqa: BLE001 - l'hook non deve mai fallire
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

```python
#!/usr/bin/env python3
# bin/claude-telegram
"""Daemon Telegram per Claude Code."""
import pathlib
import sys

REPO_LIB = pathlib.Path("/home/luca/.local/lib/claude-telegram")
if REPO_LIB.is_dir():
    sys.path.insert(0, str(REPO_LIB))

from ctg import daemon  # noqa: E402

if __name__ == "__main__":
    sys.exit(daemon.main(sys.argv[1:]))
```

L'import di `ctg` sta dentro `main` in `claude-tg-hook`: se il package è assente o rotto, l'hook esce comunque `0` invece di sollevare all'avvio. `PYTHONPATH` impostato dai test ha la precedenza su `REPO_LIB`, che nei test non esiste.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd ~/Project/personal/claude-telegram
chmod +x bin/claude-tg-hook bin/claude-telegram
python3 -m unittest tests.test_hook_entrypoint -v
```
Expected: PASS, 6 test

Misura del costo a vuoto, deve stare sotto i 200 ms:

```bash
CTG_HOME=/tmp/vuoto time bin/claude-tg-hook <<< '{"hook_event_name":"Stop"}'
```

- [ ] **Step 5: Commit**

```bash
cd ~/Project/personal/claude-telegram
git add bin/claude-tg-hook bin/claude-telegram tests/test_hook_entrypoint.py
git commit -m "feat: entrypoint degli hook e launcher del daemon"
```

---

### Task 10: Bootstrap del chat_id

**Files:**
- Create: `bin/ctg-bootstrap`
- Test: `tests/test_bootstrap.py`

**Interfaces:**
- Consumes: `ctg.config.home`, `ctg.telegram.Client`.
- Produces: `ctg.bootstrap.first_chat_id(updates: list[dict]) -> int | None` e `ctg.bootstrap.write_config(path, token: str, chat_id: int) -> None`.
- Create: `ctg/bootstrap.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bootstrap.py
import json
import pathlib
import tempfile
import unittest

from ctg import bootstrap, config


class TestFirstChatId(unittest.TestCase):
    def test_prende_il_primo_messaggio(self):
        updates = [
            {"update_id": 1, "message": {"chat": {"id": 77}, "text": "/start"}},
            {"update_id": 2, "message": {"chat": {"id": 88}, "text": "ciao"}},
        ]
        self.assertEqual(bootstrap.first_chat_id(updates), 77)

    def test_ignora_update_senza_chat(self):
        self.assertEqual(
            bootstrap.first_chat_id([{"update_id": 1}, {"update_id": 2, "message": {"chat": {"id": 5}}}]),
            5,
        )

    def test_nessun_messaggio(self):
        self.assertIsNone(bootstrap.first_chat_id([]))


class TestWriteConfig(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self._tmp.name) / "config.json"
        self.addCleanup(self._tmp.cleanup)

    def test_scrive_con_permessi_0600(self):
        bootstrap.write_config(self.path, "TOK", 77)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_il_file_scritto_e_caricabile(self):
        bootstrap.write_config(self.path, "TOK", 77)
        cfg = config.load(self.path)
        self.assertEqual(cfg["bot_token"], "TOK")
        self.assertEqual(cfg["chat_id"], 77)

    def test_preserva_le_chiavi_gia_presenti(self):
        self.path.write_text(json.dumps({"stop_threshold_seconds": 45}))
        self.path.chmod(0o600)
        bootstrap.write_config(self.path, "TOK", 77)
        self.assertEqual(config.load(self.path)["stop_threshold_seconds"], 45)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Project/personal/claude-telegram && python3 -m unittest tests.test_bootstrap -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'ctg.bootstrap'`

- [ ] **Step 3: Write minimal implementation**

```python
# ctg/bootstrap.py
import json
import os
import pathlib


def first_chat_id(updates):
    for update in updates:
        chat = ((update.get("message") or {}).get("chat")) or {}
        if "id" in chat:
            return chat["id"]
    return None


def write_config(path, token, chat_id):
    path = pathlib.Path(path)
    try:
        existing = json.loads(path.read_text())
    except (OSError, ValueError):
        existing = {}
    if not isinstance(existing, dict):
        existing = {}
    existing["bot_token"] = token
    existing["chat_id"] = chat_id
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(existing, indent=2))
    tmp.chmod(0o600)
    os.replace(tmp, path)
```

Il `chmod` avviene sul file temporaneo prima di `os.replace`, quindi il file non esiste mai con permessi larghi al path finale.

```python
#!/usr/bin/env python3
# bin/ctg-bootstrap
"""Cattura il chat_id: chiede il token, attende un messaggio al bot, scrive config.json."""
import getpass
import pathlib
import sys
import time

REPO_LIB = pathlib.Path("/home/luca/.local/lib/claude-telegram")
if REPO_LIB.is_dir():
    sys.path.insert(0, str(REPO_LIB))

from ctg import bootstrap, config, telegram  # noqa: E402

ATTEMPTS = 20


def main():
    token = getpass.getpass("Token del bot (non viene mostrato): ").strip()
    if not token:
        print("token vuoto, interrotto")
        return 1
    client = telegram.Client(token)
    print("Manda /start al bot da Telegram. Attendo.")
    for _ in range(ATTEMPTS):
        try:
            updates = client.get_updates(offset=0, timeout=15)
        except telegram.TelegramError as exc:
            print(f"errore: {exc}")
            return 1
        chat_id = bootstrap.first_chat_id(updates)
        if chat_id is not None:
            path = config.config_path()
            bootstrap.write_config(path, token, chat_id)
            print(f"chat_id {chat_id} scritto in {path}")
            return 0
        time.sleep(1)
    print("nessun messaggio ricevuto, riprova")
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd ~/Project/personal/claude-telegram
chmod +x bin/ctg-bootstrap
python3 -m unittest tests.test_bootstrap -v
```
Expected: PASS, 6 test

- [ ] **Step 5: Commit**

```bash
cd ~/Project/personal/claude-telegram
git add ctg/bootstrap.py bin/ctg-bootstrap tests/test_bootstrap.py
git commit -m "feat: bootstrap interattivo per token e chat_id"
```

---

### Task 11: Unit systemd e installazione

**Files:**
- Create: `systemd/claude-telegram.service`
- Create: `install.sh`
- Modify: `README.md`

**Interfaces:**
- Consumes: tutti i file dei task precedenti.
- Produces: `install.sh` idempotente, che copia il package in `~/.local/lib/claude-telegram/ctg/`, gli eseguibili in `~/bin/` e l'unit in `~/.config/systemd/user/`. Non tocca `~/.claude/settings.json`: quello è il Task 12.

- [ ] **Step 1: Write the unit and installer**

```ini
# systemd/claude-telegram.service
[Unit]
Description=Daemon Telegram per Claude Code
After=network-online.target

[Service]
Type=simple
ExecStart=%h/bin/claude-telegram
Restart=on-failure
RestartSec=5
# Il daemon legge config.json e scrive stato solo sotto ~/.claude/telegram.
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=default.target
```

```bash
#!/usr/bin/env bash
# install.sh — copia il codice nelle posizioni di esecuzione. Idempotente.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
lib="$HOME/.local/lib/claude-telegram"
bindir="$HOME/bin"
unitdir="$HOME/.config/systemd/user"
ctg_home="${CTG_HOME:-$HOME/.claude/telegram}"

mkdir -p "$lib" "$bindir" "$unitdir" "$ctg_home"
chmod 700 "$ctg_home"

rm -rf "$lib/ctg"
cp -r "$repo/ctg" "$lib/ctg"

for exe in claude-telegram claude-tg-hook ctg-bootstrap; do
  install -m 0755 "$repo/bin/$exe" "$bindir/$exe"
done

install -m 0644 "$repo/systemd/claude-telegram.service" "$unitdir/claude-telegram.service"
systemctl --user daemon-reload

echo "Installato."
echo "  libreria: $lib/ctg"
echo "  eseguibili: $bindir/{claude-telegram,claude-tg-hook,ctg-bootstrap}"
echo "  unit: $unitdir/claude-telegram.service"
echo
echo "Passi successivi:"
echo "  1. $bindir/ctg-bootstrap        # token e chat_id"
echo "  2. systemctl --user enable --now claude-telegram"
echo "  3. registrare gli hook in ~/.claude/settings.json"
```

- [ ] **Step 2: Verify the installer runs clean twice**

```bash
cd ~/Project/personal/claude-telegram
chmod +x install.sh
./install.sh
./install.sh
ls -l ~/bin/claude-tg-hook ~/.local/lib/claude-telegram/ctg/config.py
```
Expected: entrambe le esecuzioni terminano senza errori, i file esistono.

- [ ] **Step 3: Verify the daemon refuses to start without config**

```bash
systemctl --user start claude-telegram; sleep 2
systemctl --user status claude-telegram --no-pager | head -5
```
Expected: unit fallita, perché `config.json` non esiste ancora. È il comportamento voluto: `config.ConfigError`, non un avvio silenzioso senza token.

```bash
systemctl --user stop claude-telegram
```

- [ ] **Step 4: Update README**

Sostituire la tabella "Dove finiscono i file" nel README con:

```markdown
| dal repo | a |
|---|---|
| `ctg/` | `~/.local/lib/claude-telegram/ctg/` |
| `bin/claude-telegram` | `~/bin/` |
| `bin/claude-tg-hook` | `~/bin/` |
| `bin/ctg-bootstrap` | `~/bin/` |
| `systemd/claude-telegram.service` | `~/.config/systemd/user/` |

Installazione: `./install.sh`, idempotente.
```

- [ ] **Step 5: Commit**

```bash
cd ~/Project/personal/claude-telegram
git add systemd/claude-telegram.service install.sh README.md
git commit -m "feat: unit systemd e installer idempotente"
```

---

### Task 12: Registrazione degli hook e verifica end-to-end

**Files:**
- Modify: `/home/luca/.claude/settings.json`
- Create: `docs/verifica-piano-1.md`

**Interfaces:**
- Consumes: tutto quanto sopra.
- Produces: nessuna interfaccia di codice. Il risultato è il sistema attivo su tutte le sessioni della macchina.

Questo task modifica la configurazione che governa ogni sessione Claude Code su `home-server`, inclusa quella in cui viene eseguito. Il backup e la prova del kill switch precedono la modifica.

- [ ] **Step 1: Back up the settings and arm the kill switch**

```bash
cp ~/.claude/settings.json ~/.claude/settings.json.bak-$(date +%Y%m%d-%H%M%S)
touch ~/.claude/telegram/disabled
ls -l ~/.claude/settings.json.bak-* ~/.claude/telegram/disabled
```

Con `disabled` presente gli hook escono `0` senza fare nulla, quindi la registrazione può avvenire a sistema disarmato.

- [ ] **Step 2: Complete the bootstrap**

```bash
~/bin/ctg-bootstrap
```

Serve il telefono: creare il bot su BotFather, incollare il token quando richiesto, poi mandare `/start` al bot.

```bash
ls -l ~/.claude/telegram/config.json
```
Expected: permessi `-rw-------`.

- [ ] **Step 3: Start the daemon**

```bash
systemctl --user enable --now claude-telegram
systemctl --user status claude-telegram --no-pager | head -5
```
Expected: `Active: active (running)`.

- [ ] **Step 4: Verify the daemon answers before touching settings.json**

```bash
cd ~/Project/personal/claude-telegram
CTG_HOME=~/.claude/telegram PYTHONPATH=$PWD python3 - <<'EOF'
import os, pathlib
from ctg import ipc
print(ipc.request(pathlib.Path(os.environ["CTG_HOME"]) / "sock",
                  {"hook_event_name": "Notification", "cwd": os.getcwd(),
                   "message": "prova dal piano 1"}, timeout=5))
EOF
```
Expected: `{'sent': True, 'reason': 'inviato'}` e il messaggio arriva su Telegram. Il kill switch non interviene qui perché è controllato da `claude-tg-hook`, non dal daemon.

Se il messaggio non arriva, fermarsi: `settings.json` non va toccato finché il trasporto non funziona.

- [ ] **Step 5: Register the hooks**

Aggiungere a `~/.claude/settings.json`, allo stesso livello di `"model"` e `"statusLine"`:

```json
"hooks": {
  "Notification": [
    {"hooks": [{"type": "command", "command": "$HOME/bin/claude-tg-hook", "timeout": 5}]}
  ],
  "Stop": [
    {"hooks": [{"type": "command", "command": "$HOME/bin/claude-tg-hook", "timeout": 5}]}
  ],
  "UserPromptSubmit": [
    {"hooks": [{"type": "command", "command": "$HOME/bin/claude-tg-hook", "timeout": 5}]}
  ]
}
```

Validare prima di considerare fatto il passo:

```bash
python3 -c "import json;json.load(open('/home/luca/.claude/settings.json'));print('JSON valido')"
```
Expected: `JSON valido`. Se fallisce, ripristinare dal backup del passo 1.

- [ ] **Step 6: Disarm the kill switch and test with a real session**

```bash
rm ~/.claude/telegram/disabled
```

In una sessione Claude Code nuova, per esempio `tmux attach -t rc-personal`:

1. Fare una domanda che si risolve in pochi secondi. Atteso: **nessun** messaggio Telegram.
2. Lanciare un lavoro che supera i 120 s. Atteso: un messaggio `[personal] finito` con le ultime righe della risposta.
3. Provocare una richiesta di permesso. Atteso: un messaggio `[<progetto>] permesso richiesto`.
4. Mandare `/stato` al bot. Atteso: uptime e lista delle sessioni tmux.

- [ ] **Step 7: Verify the reboot survives**

```bash
systemctl --user is-enabled claude-telegram
loginctl show-user luca --property=Linger
```
Expected: `enabled` e `Linger=yes`.

- [ ] **Step 8: Write the verification record and commit**

Creare `docs/verifica-piano-1.md` con l'esito di ciascun controllo del passo 6, la data e l'output osservato.

```bash
cd ~/Project/personal/claude-telegram
git add docs/verifica-piano-1.md
git commit -m "docs: esito della verifica end-to-end del piano 1"
```

---

## Fuori ambito per questo piano

- `sendDocument` e il comando `/file`: piano 2.
- Iniezione in tmux e comandi `/sessioni`, `/s`: piano 2.
- Shim `claude-sudo`, wrapper root, TOTP, sudoers, cache delle approvazioni: piano 3.
- Il flag `from_telegram` di `should_notify_stop` esiste già ma nessuno lo passa `True` finché il piano 2 non introduce le richieste da Telegram.
