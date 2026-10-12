"""Encryption of ``secret`` plugin settings (API keys) at rest.

A secret is stored as ``plugin-secret:<Fernet token>`` in the installation's settings, with a key
derived from Django's ``SECRET_KEY`` for this purpose only. It is decrypted solely by the code that
uses it (never for display, rendering to engine files, or the audit trail).
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

PREFIX = 'plugin-secret:'
MASK = '•••• set'


def _fernet() -> Fernet:
    seed = f'plugin-secret:{settings.SECRET_KEY}'.encode()
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(seed).digest()))


def is_encrypted(value: object) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def encrypt(plain: str) -> str:
    return PREFIX + _fernet().encrypt(plain.encode('utf-8')).decode('ascii')


def decrypt(stored: str) -> str:
    """The plain secret. Raises ``ValueError`` when it cannot be read (e.g. SECRET_KEY changed)."""
    if not is_encrypted(stored):
        raise ValueError('not an encrypted plugin secret')
    try:
        return _fernet().decrypt(stored[len(PREFIX) :].encode('ascii')).decode('utf-8')
    except (InvalidToken, ValueError) as exc:
        raise ValueError('the stored secret cannot be decrypted; enter it again') from exc
