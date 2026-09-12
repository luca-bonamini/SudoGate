import json
import urllib.error
import urllib.request

API_BASE = "https://api.telegram.org"
CALLBACK_DATA_MAX = 64


class TelegramError(Exception):
    """The Telegram API rejected the call, or could not be reached."""


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
            raise TelegramError(f"{method} unreachable: {exc.reason}") from None
        except (OSError, ValueError):
            raise TelegramError(f"{method} returned an unreadable response") from None
        if not body.get("ok"):
            raise TelegramError(f"{method}: {body.get('description', 'response not ok')}")
        return body["result"]


def _keyboard(rows):
    keyboard = []
    for row in rows:
        cells = []
        for label, data in row:
            encoded = data.encode()
            if len(encoded) > CALLBACK_DATA_MAX:
                raise ValueError(
                    f"callback_data is {len(encoded)} bytes, the maximum is {CALLBACK_DATA_MAX}"
                )
            cells.append({"text": label, "callback_data": data})
        keyboard.append(cells)
    return keyboard
