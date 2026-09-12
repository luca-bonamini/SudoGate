"""TOTP secondo RFC 6238, solo standard library.

Usato dal wrapper root per verificare il secondo fattore sui comandi
distruttivi. Il seed non lascia mai /etc/claude-gate/seed: l'utente luca
puo inoltrare un codice, non calcolarne uno valido.
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
import urllib.parse

DEFAULT_DIGITS = 6
DEFAULT_PERIOD = 30
DEFAULT_WINDOW = 1


def _hotp(key, counter, digits):
    message = struct.pack(">Q", counter)
    digest = hmac.new(key, message, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(binary % (10 ** digits)).zfill(digits)


def _decode_secret(secret_b32):
    padded = secret_b32.strip().replace(" ", "").upper()
    padded += "=" * (-len(padded) % 8)
    return base64.b32decode(padded)


def generate(secret_b32, at_time=None, digits=DEFAULT_DIGITS, period=DEFAULT_PERIOD):
    at_time = time.time() if at_time is None else at_time
    counter = int(at_time) // period
    return _hotp(_decode_secret(secret_b32), counter, digits)


def verify(
    secret_b32,
    code,
    at_time=None,
    digits=DEFAULT_DIGITS,
    period=DEFAULT_PERIOD,
    window=DEFAULT_WINDOW,
):
    cleaned = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(cleaned) != digits:
        return False
    at_time = time.time() if at_time is None else at_time
    key = _decode_secret(secret_b32)
    base = int(at_time) // period
    ok = False
    # Confronto su tutta la finestra senza short-circuit: tempo costante
    # rispetto a quale periodo combacia.
    for step in range(-window, window + 1):
        candidate = _hotp(key, base + step, digits)
        if hmac.compare_digest(candidate, cleaned):
            ok = True
    return ok


def new_secret(length_bytes=20):
    return base64.b32encode(secrets.token_bytes(length_bytes)).decode().rstrip("=")


def provisioning_uri(secret_b32, label, issuer):
    label_enc = urllib.parse.quote(f"{issuer}:{label}")
    params = urllib.parse.urlencode(
        {"secret": secret_b32, "issuer": issuer, "algorithm": "SHA1",
         "digits": DEFAULT_DIGITS, "period": DEFAULT_PERIOD}
    )
    return f"otpauth://totp/{label_enc}?{params}"
