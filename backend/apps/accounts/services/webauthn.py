"""WebAuthn (passkeys): the parts of the protocol this server must check itself.

A browser and an authenticator do the cryptography on their side; the server's job is to hand out a
random challenge, then verify what comes back: that the response answers *this* challenge, was made
for *this* origin and relying party, proved the person was present and verified (a PIN or a
biometric), and was signed by the key it registered. That is what this module does, with
``cryptography`` (already a dependency) for the signatures and a small CBOR reader for the two
structures the protocol wraps (the attestation object and the COSE public key).

It is deliberately pure: bytes in, a verified result or ``WebAuthnError`` out. No Django, no
database, so every rule below is testable with a software authenticator.

Scope, stated plainly: attestation statements are not trusted or checked (``attestation: "none"``
is requested; passkeys are trust-on-first-use, which is how consumer passkeys work). User
verification is required for every registration and every sign-in, which is what makes a passkey
sign-in a second factor on its own.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import struct
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa

# COSE algorithm identifiers (RFC 9053 / WebAuthn registry) this server accepts.
ES256, EDDSA, RS256 = -7, -8, -257
SUPPORTED_ALGORITHMS = (ES256, EDDSA, RS256)

FLAG_UP = 0x01  # user present
FLAG_UV = 0x04  # user verified (PIN, biometric)
FLAG_BE = 0x08  # backup eligible (a synced passkey)
FLAG_BS = 0x10  # currently backed up
FLAG_AT = 0x40  # attested credential data follows

MAX_CBOR_DEPTH = 8
MAX_CBOR_ITEMS = 256
MAX_CREDENTIAL_ID = 1023  # WebAuthn: at most 1023 bytes


class WebAuthnError(ValueError):
    """A response that cannot be accepted (the message is safe to show to the person)."""


# -- base64url ---------------------------------------------------------------------------------


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def b64url_decode(text: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))
    except (ValueError, TypeError) as exc:
        raise WebAuthnError('The response was not valid base64.') from exc


# -- CBOR (the subset WebAuthn uses) -----------------------------------------------------------


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0
        self.items = 0

    def take(self, n: int) -> bytes:
        if n < 0 or self.pos + n > len(self.data):
            raise WebAuthnError('The response was truncated.')
        chunk = self.data[self.pos : self.pos + n]
        self.pos += n
        return chunk

    def argument(self, info: int) -> int:
        if info < 24:
            return info
        size = {24: 1, 25: 2, 26: 4, 27: 8}.get(info)
        if size is None:
            raise WebAuthnError('The response used an unsupported encoding.')
        return int.from_bytes(self.take(size), 'big')

    def item(self, depth: int = 0) -> Any:
        if depth > MAX_CBOR_DEPTH:
            raise WebAuthnError('The response was nested too deeply.')
        self.items += 1
        if self.items > MAX_CBOR_ITEMS:
            raise WebAuthnError('The response was too large.')
        head = self.take(1)[0]
        major, info = head >> 5, head & 0x1F
        if major == 0:
            return self.argument(info)
        if major == 1:
            return -1 - self.argument(info)
        if major in (2, 3):
            length = self.argument(info)
            raw = self.take(length)
            if major == 2:
                return raw
            try:
                return raw.decode('utf-8')
            except UnicodeDecodeError as exc:
                raise WebAuthnError('The response contained invalid text.') from exc
        if major == 4:
            return [self.item(depth + 1) for _ in range(self.argument(info))]
        if major == 5:
            out: dict[Any, Any] = {}
            for _ in range(self.argument(info)):
                key = self.item(depth + 1)
                if not isinstance(key, (int, str, bytes)):
                    raise WebAuthnError('The response used an unsupported key.')
                out[key] = self.item(depth + 1)
            return out
        if major == 7:
            if info in (20, 21):
                return info == 21
            if info == 22:
                return None
        raise WebAuthnError('The response used an unsupported encoding.')


def cbor_decode(data: bytes) -> Any:
    """Decode one CBOR item that must span all of ``data``."""
    reader = _Reader(data)
    value = reader.item()
    if reader.pos != len(data):
        raise WebAuthnError('The response had trailing data.')
    return value


def cbor_decode_prefix(data: bytes) -> tuple[Any, int]:
    """Decode one item from the start of ``data``; returns ``(value, bytes_used)``."""
    reader = _Reader(data)
    return reader.item(), reader.pos


# -- authenticator data -------------------------------------------------------------------------


@dataclass(frozen=True)
class AuthenticatorData:
    rp_id_hash: bytes
    flags: int
    sign_count: int
    credential_id: bytes = b''
    aaguid: bytes = b''
    public_key: bytes = b''  # the COSE key, exactly as the authenticator sent it
    algorithm: int = 0

    @property
    def user_present(self) -> bool:
        return bool(self.flags & FLAG_UP)

    @property
    def user_verified(self) -> bool:
        return bool(self.flags & FLAG_UV)

    @property
    def backup_eligible(self) -> bool:
        return bool(self.flags & FLAG_BE)

    @property
    def backed_up(self) -> bool:
        return bool(self.flags & FLAG_BS)


def parse_authenticator_data(data: bytes, *, expect_credential: bool) -> AuthenticatorData:
    if len(data) < 37:
        raise WebAuthnError('The authenticator data was too short.')
    rp_hash, flags, count = data[:32], data[32], struct.unpack('>I', data[33:37])[0]
    if not flags & FLAG_AT:
        if expect_credential:
            raise WebAuthnError('The response carried no new credential.')
        return AuthenticatorData(rp_hash, flags, count)
    rest = data[37:]
    if len(rest) < 18:
        raise WebAuthnError('The credential data was too short.')
    aaguid = rest[:16]
    length = struct.unpack('>H', rest[16:18])[0]
    if length == 0 or length > MAX_CREDENTIAL_ID or len(rest) < 18 + length:
        raise WebAuthnError('The credential id had an invalid length.')
    credential_id = rest[18 : 18 + length]
    key_bytes = rest[18 + length :]
    key, used = cbor_decode_prefix(key_bytes)
    if not isinstance(key, dict) or not isinstance(key.get(3), int):
        raise WebAuthnError('The public key was not a COSE key.')
    algorithm = key[3]
    if algorithm not in SUPPORTED_ALGORITHMS:
        raise WebAuthnError('This passkey uses an algorithm this server does not accept.')
    public_key = key_bytes[:used]
    _public_key_object(public_key)  # reject a malformed key now, not at the first sign-in
    return AuthenticatorData(rp_hash, flags, count, credential_id, aaguid, public_key, algorithm)


# -- keys and signatures ------------------------------------------------------------------------


def _public_key_object(cose: bytes) -> Any:
    key = cbor_decode(cose)
    if not isinstance(key, dict):
        raise WebAuthnError('The public key was malformed.')
    try:
        kty, alg = key[1], key[3]
        if alg == ES256 and kty == 2 and key.get(-1) == 1:
            x, y = key[-2], key[-3]
            if not (isinstance(x, bytes) and isinstance(y, bytes) and len(x) == len(y) == 32):
                raise WebAuthnError('The public key was malformed.')
            numbers = ec.EllipticCurvePublicNumbers(
                int.from_bytes(x, 'big'), int.from_bytes(y, 'big'), ec.SECP256R1()
            )
            return numbers.public_key()
        if alg == EDDSA and kty == 1 and key.get(-1) == 6:
            raw = key[-2]
            if not (isinstance(raw, bytes) and len(raw) == 32):
                raise WebAuthnError('The public key was malformed.')
            return ed25519.Ed25519PublicKey.from_public_bytes(raw)
        if alg == RS256 and kty == 3:
            n, e = key[-1], key[-2]
            if not (isinstance(n, bytes) and isinstance(e, bytes)) or not 256 <= len(n) <= 1024:
                raise WebAuthnError('The public key was malformed.')
            return rsa.RSAPublicNumbers(
                int.from_bytes(e, 'big'), int.from_bytes(n, 'big')
            ).public_key()
    except (KeyError, ValueError, TypeError) as exc:
        raise WebAuthnError('The public key was malformed.') from exc
    raise WebAuthnError('The public key type is not supported.')


def verify_signature(cose: bytes, signature: bytes, signed: bytes) -> None:
    key = _public_key_object(cose)
    algorithm = cbor_decode(cose)[3]
    try:
        if algorithm == ES256:
            key.verify(signature, signed, ec.ECDSA(hashes.SHA256()))
        elif algorithm == EDDSA:
            key.verify(signature, signed)
        else:
            key.verify(signature, signed, padding.PKCS1v15(), hashes.SHA256())
    except (InvalidSignature, ValueError) as exc:
        raise WebAuthnError('The signature did not match this passkey.') from exc


# -- client data --------------------------------------------------------------------------------


def _client_data(raw: bytes, *, kind: str, challenge: bytes, origin: str) -> None:
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise WebAuthnError('The client data was not valid.') from exc
    if not isinstance(data, dict) or data.get('type') != kind:
        raise WebAuthnError('The response was for a different request.')
    given = data.get('challenge')
    if not isinstance(given, str) or not hmac.compare_digest(given, b64url_encode(challenge)):
        raise WebAuthnError('The challenge did not match. Start again.')
    if data.get('origin') != origin:
        raise WebAuthnError('The response was made for a different site.')
    if data.get('crossOrigin') is True:
        raise WebAuthnError('The response came from another site’s frame.')


def _check_rp(auth: AuthenticatorData, rp_id: str) -> None:
    if not hmac.compare_digest(auth.rp_id_hash, hashlib.sha256(rp_id.encode()).digest()):
        raise WebAuthnError('The passkey was made for a different domain.')
    if not auth.user_present or not auth.user_verified:
        raise WebAuthnError('The passkey was not unlocked with a PIN, fingerprint or face.')


# -- the two ceremonies --------------------------------------------------------------------------


@dataclass(frozen=True)
class Registration:
    credential_id: bytes
    public_key: bytes
    algorithm: int
    sign_count: int
    aaguid: bytes
    backup_eligible: bool
    backed_up: bool


def verify_registration(
    *, client_data_json: bytes, attestation_object: bytes, challenge: bytes, origin: str, rp_id: str
) -> Registration:
    _client_data(client_data_json, kind='webauthn.create', challenge=challenge, origin=origin)
    attestation = cbor_decode(attestation_object)
    if not isinstance(attestation, dict) or not isinstance(attestation.get('authData'), bytes):
        raise WebAuthnError('The attestation was not valid.')
    auth = parse_authenticator_data(attestation['authData'], expect_credential=True)
    _check_rp(auth, rp_id)
    return Registration(
        auth.credential_id,
        auth.public_key,
        auth.algorithm,
        auth.sign_count,
        auth.aaguid,
        auth.backup_eligible,
        auth.backed_up,
    )


@dataclass(frozen=True)
class Assertion:
    sign_count: int
    backup_eligible: bool
    backed_up: bool


def verify_assertion(
    *,
    client_data_json: bytes,
    authenticator_data: bytes,
    signature: bytes,
    public_key: bytes,
    challenge: bytes,
    origin: str,
    rp_id: str,
) -> Assertion:
    _client_data(client_data_json, kind='webauthn.get', challenge=challenge, origin=origin)
    auth = parse_authenticator_data(authenticator_data, expect_credential=False)
    _check_rp(auth, rp_id)
    signed = authenticator_data + hashlib.sha256(client_data_json).digest()
    verify_signature(public_key, signature, signed)
    return Assertion(auth.sign_count, auth.backup_eligible, auth.backed_up)


def counter_regressed(stored: int, presented: int) -> bool:
    """A cloned authenticator shows up as a counter that does not move forward.

    Many passkeys (synced ones especially) always report 0; those are not judged. Once a counter
    is in use, every sign-in must exceed the stored one.
    """
    return (stored > 0 or presented > 0) and presented <= stored


# -- helpers for tests and options ----------------------------------------------------------------


def generate_challenge() -> bytes:
    import secrets

    return secrets.token_bytes(32)


def is_ip_address(host: str) -> bool:
    import ipaddress

    try:
        ipaddress.ip_address(host.strip('[]'))
        return True
    except ValueError:
        return False
