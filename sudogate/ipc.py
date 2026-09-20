"""Line-delimited JSON over a Unix socket, between the shim and the daemon.

The daemon runs under its own system account and the shim runs as the human
user, so the socket is the boundary between an untrusted caller and the
component that decides. Every connection is identified with SO_PEERCRED: the
kernel fills those credentials in, the caller cannot choose them, and a
request from any account other than the gated one is dropped before the
handler sees it — and so before anything reaches the phone.
"""
import json
import os
import pathlib
import socket
import struct

ACCEPT_POLL_SECONDS = 0.5
CONNECTION_TIMEOUT_SECONDS = 130
MAX_LINE_BYTES = 1_048_576

_UCRED = struct.Struct("3i")


class IPCError(Exception):
    """The daemon is not answering, or answered with something unreadable."""


class Peer:
    """Kernel-attested identity of the process on the other end."""

    __slots__ = ("pid", "uid", "gid")

    def __init__(self, pid, uid, gid):
        self.pid, self.uid, self.gid = pid, uid, gid

    def __repr__(self):
        return f"Peer(pid={self.pid}, uid={self.uid}, gid={self.gid})"


def peer_of(conn):
    raw = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, _UCRED.size)
    return Peer(*_UCRED.unpack(raw))


def request(sock_path, payload, timeout):
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout)
    try:
        client.connect(str(sock_path))
        client.sendall((json.dumps(payload) + "\n").encode())
        return json.loads(_read_line(client))
    except (OSError, ValueError) as exc:
        raise IPCError(f"request to the daemon failed: {exc}") from None
    finally:
        client.close()


def serve(sock_path, handler, stop_event, on_ready=None, allowed_uids=None, mode=0o600):
    """Serve requests until stop_event is set.

    handler is called as handler(payload, peer). allowed_uids, when given,
    is the set of uids permitted to make requests; anyone else is refused
    without reaching the handler.
    """
    path = pathlib.Path(sock_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(str(path))
        os.chmod(path, mode)
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
                _handle(conn, handler, allowed_uids)
    finally:
        server.close()
        if path.exists():
            path.unlink()


def _handle(conn, handler, allowed_uids):
    conn.settimeout(CONNECTION_TIMEOUT_SECONDS)
    try:
        peer = peer_of(conn)
    except OSError:
        return
    if allowed_uids is not None and peer.uid not in allowed_uids:
        _send(conn, {"verdict": "deny", "reason": f"uid {peer.uid} is not the gated account"})
        return
    try:
        payload = json.loads(_read_line(conn))
    except (OSError, ValueError):
        return
    try:
        reply = handler(payload, peer)
    except Exception as exc:  # noqa: BLE001 - a broken handler must not stop the server
        reply = {"error": str(exc)}
    _send(conn, reply)


def _send(conn, reply):
    try:
        conn.sendall((json.dumps(reply) + "\n").encode())
    except OSError:
        pass


def _read_line(sock):
    buffer = b""
    while not buffer.endswith(b"\n"):
        chunk = sock.recv(4096)
        if not chunk:
            raise OSError("connection closed before the response ended")
        buffer += chunk
        if len(buffer) > MAX_LINE_BYTES:
            raise OSError("response larger than 1 MB")
    return buffer.decode()
