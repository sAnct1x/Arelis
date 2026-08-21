"""End-to-end box for the mailbox. The relay never sees this key.

Derived from the ingest token and instance already in the pairing QR.
AES-GCM; AAD binds the blob to that instance so it cannot be replayed
onto a different house.
"""

from __future__ import annotations

import hashlib
import hmac
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

INFO = b"arelis-e2e-v1"
NONCE_LEN = 12
KEY_LEN = 32


def hkdf_sha256(
    ikm: bytes, *, salt: bytes, info: bytes, length: int = KEY_LEN
) -> bytes:
    if not salt:
        salt = b"\x00" * hashlib.sha256().digest_size
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    okm = b""
    prev = b""
    counter = 1
    while len(okm) < length:
        prev = hmac.new(prk, prev + info + bytes([counter]), hashlib.sha256).digest()
        okm += prev
        counter += 1
    return okm[:length]


def e2e_key(token: str, instance: str) -> bytes:
    return hkdf_sha256(
        (token or "").encode(),
        salt=(instance or "").encode(),
        info=INFO,
        length=KEY_LEN,
    )


def seal(key: bytes, plaintext: bytes, *, aad: bytes) -> bytes:
    nonce = os.urandom(NONCE_LEN)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, aad)


def open_box(key: bytes, blob: bytes, *, aad: bytes) -> bytes:
    if len(blob) < NONCE_LEN + 16:
        raise ValueError("short box")
    nonce, ct = blob[:NONCE_LEN], blob[NONCE_LEN:]
    return AESGCM(key).decrypt(nonce, ct, aad)
