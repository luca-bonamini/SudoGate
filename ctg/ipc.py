import json
import os
import pathlib
import socket

ACCEPT_POLL_SECONDS = 0.5
CONNECTION_TIMEOUT_SECONDS = 130
MAX_LINE_BYTES = 1_048_576


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
    conn.settimeout(CONNECTION_TIMEOUT_SECONDS)
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
        if len(buffer) > MAX_LINE_BYTES:
            raise OSError("risposta oltre 1 MB")
    return buffer.decode()
