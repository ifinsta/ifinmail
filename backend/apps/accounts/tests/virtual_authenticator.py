"""A software WebAuthn authenticator for tests: makes passkeys and signs sign-in challenges.

It speaks the same bytes a browser forwards from a real authenticator, so the server's checks are
exercised end to end without a browser: CBOR attestation objects, authenticator data with flags
and counter, clientDataJSON, and real ES256 / Ed25519 / RS256 signatures.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa

from backend.apps.accounts.services.webauthn import (
    EDDSA,
    ES256,
    FLAG_AT,
    FLAG_BE,
    FLAG_UP,
    FLAG_UV,
    RS256,
    b64url_decode,
    b64url_encode,
)


def cbor(value: Any) -> bytes:
    def head(major: int, n: int) -> bytes:
        if n < 24:
            return bytes([major << 5 | n])
        if n < 256:
            return bytes([major << 5 | 24, n])
        if n < 65536:
            return bytes([major << 5 | 25]) + struct.pack('>H', n)
        return bytes([major << 5 | 26]) + struct.pack('>I', n)

    if isinstance(value, bool):
        return bytes([0xF5 if value else 0xF4])
    if isinstance(value, int):
        return head(0, value) if value >= 0 else head(1, -1 - value)
    if isinstance(value, bytes):
        return head(2, len(value)) + value
    if isinstance(value, str):
        raw = value.encode()
        return head(3, len(raw)) + raw
    if isinstance(value, list):
        return head(4, len(value)) + b''.join(cbor(v) for v in value)
    if isinstance(value, dict):
        return head(5, len(value)) + b''.join(cbor(k) + cbor(v) for k, v in value.items())
    raise TypeError(type(value))


class VirtualAuthenticator:
    def __init__(self, algorithm: int = ES256, *, synced: bool = False, counter: int = 1) -> None:
        self.algorithm = algorithm
        self.credential_id = os.urandom(32)
        self.counter = counter
        self.synced = synced
        self.aaguid = os.urandom(16)
        if algorithm == ES256:
            self.key: Any = ec.generate_private_key(ec.SECP256R1())
        elif algorithm == EDDSA:
            self.key = ed25519.Ed25519PrivateKey.generate()
        else:
            self.key = rsa.generate_private_key(65537, 2048)

    # -- the COSE public key --------------------------------------------------------------------
    def cose_key(self) -> bytes:
        if self.algorithm == ES256:
            n = self.key.public_key().public_numbers()
            return cbor(
                {1: 2, 3: ES256, -1: 1, -2: n.x.to_bytes(32, 'big'), -3: n.y.to_bytes(32, 'big')}
            )
        if self.algorithm == EDDSA:
            raw = self.key.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            )
            return cbor({1: 1, 3: EDDSA, -1: 6, -2: raw})
        n = self.key.public_key().public_numbers()
        return cbor({1: 3, 3: RS256, -1: n.n.to_bytes(256, 'big'), -2: n.e.to_bytes(3, 'big')})

    # -- helpers -------------------------------------------------------------------------------
    def flags(self, *, up: bool = True, uv: bool = True, at: bool = False) -> int:
        return (
            (FLAG_UP if up else 0)
            | (FLAG_UV if uv else 0)
            | (FLAG_AT if at else 0)
            | (FLAG_BE if self.synced else 0)
        )

    def auth_data(
        self, rp_id: str, *, counter: int | None = None, at: bool = False, **kw: bool
    ) -> bytes:
        data = hashlib.sha256(rp_id.encode()).digest()
        data += bytes([self.flags(at=at, **kw)])
        data += struct.pack('>I', self.counter if counter is None else counter)
        if at:
            data += self.aaguid + struct.pack('>H', len(self.credential_id)) + self.credential_id
            data += self.cose_key()
        return data

    @staticmethod
    def client_data(kind: str, challenge: str, origin: str, **extra: Any) -> bytes:
        return json.dumps(
            {'type': kind, 'challenge': challenge, 'origin': origin, 'crossOrigin': False, **extra}
        ).encode()

    def sign(self, message: bytes) -> bytes:
        if self.algorithm == ES256:
            return self.key.sign(message, ec.ECDSA(hashes.SHA256()))
        if self.algorithm == EDDSA:
            return self.key.sign(message)
        return self.key.sign(message, padding.PKCS1v15(), hashes.SHA256())

    # -- the two ceremonies -------------------------------------------------------------------
    def create(
        self,
        options: dict[str, Any],
        *,
        origin: str = 'https://testserver',
        rp_id: str | None = None,
        **flag_overrides: bool,
    ) -> dict[str, Any]:
        rp = rp_id or options['rp']['id']
        auth = self.auth_data(rp, at=True, **flag_overrides)
        attestation = cbor({'fmt': 'none', 'attStmt': {}, 'authData': auth})
        client = self.client_data('webauthn.create', options['challenge'], origin)
        return {
            'id': b64url_encode(self.credential_id),
            'rawId': b64url_encode(self.credential_id),
            'type': 'public-key',
            'response': {
                'clientDataJSON': b64url_encode(client),
                'attestationObject': b64url_encode(attestation),
                'transports': ['internal'],
            },
        }

    def get(
        self,
        options: dict[str, Any],
        *,
        user_handle: bytes | None = None,
        origin: str = 'https://testserver',
        rp_id: str | None = None,
        counter: int | None = None,
        tamper_signature: bool = False,
        **flag_overrides: bool,
    ) -> dict[str, Any]:
        rp = rp_id or options['rpId']
        if counter is None:
            self.counter += 1
        auth = self.auth_data(rp, counter=counter, **flag_overrides)
        client = self.client_data('webauthn.get', options['challenge'], origin)
        signature = self.sign(auth + hashlib.sha256(client).digest())
        if tamper_signature:
            signature = signature[:-1] + bytes([signature[-1] ^ 0xFF])
        return {
            'id': b64url_encode(self.credential_id),
            'rawId': b64url_encode(self.credential_id),
            'type': 'public-key',
            'response': {
                'clientDataJSON': b64url_encode(client),
                'authenticatorData': b64url_encode(auth),
                'signature': b64url_encode(signature),
                'userHandle': b64url_encode(user_handle) if user_handle else '',
            },
        }


def decode(text: str) -> bytes:
    return b64url_decode(text)
