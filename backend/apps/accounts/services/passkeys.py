"""Passkeys for console sign-in: the ceremonies, the challenge bookkeeping, the stored credentials.

Two ways a passkey signs someone in, both requiring the authenticator to verify the person (a PIN,
a fingerprint or a face), which is what makes it a second factor in its own right:

* **Passwordless**: "Sign in with a passkey" on the login page. The browser offers the passkeys it
  holds for this site (discoverable credentials); no email or password is typed.
* **Second step**: someone who typed a correct password and has a passkey proves it instead of
  entering a code.

The protocol checks are in ``webauthn``; this module adds what needs the request, the session and
the database: which domain and origin the console runs on, one-time challenges kept in the session,
the stored credentials and their counters.
"""

from __future__ import annotations

import json
import time
from typing import Any

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.http import HttpRequest
from django.utils import timezone

from backend.apps.accounts.models import Passkey
from backend.apps.accounts.services import webauthn
from backend.apps.accounts.services.webauthn import WebAuthnError, b64url_decode, b64url_encode

CHALLENGE_TTL = 300  # seconds a challenge may be answered in
MAX_PER_USER = 10
_REGISTER = 'passkey_register_challenge'
_SIGN_IN = 'passkey_signin_challenge'
_PUBKEY_PARAMS = [
    {'type': 'public-key', 'alg': webauthn.ES256},
    {'type': 'public-key', 'alg': webauthn.EDDSA},
    {'type': 'public-key', 'alg': webauthn.RS256},
]


class PasskeyError(WebAuthnError):
    """A passkey request that cannot be fulfilled (the message is safe to show)."""


# -- where the console is ------------------------------------------------------------------------


def relying_party(request: HttpRequest) -> tuple[str, str]:
    """``(rp_id, origin)`` for this request: the console's own host, never one a client chose.

    ``request.get_host()`` is already checked against ALLOWED_HOSTS. Passkeys are bound to a
    domain name, so a bare IP address cannot be used.
    """
    host = request.get_host()
    name = host.rsplit(':', 1)[0] if host.count(':') == 1 else host
    if webauthn.is_ip_address(name):
        raise PasskeyError(
            'Passkeys work on the console’s domain name, not an IP address. '
            'Open the console at its https:// name and try again.'
        )
    scheme = 'https' if request.is_secure() else 'http'
    if scheme == 'http' and name != 'localhost':
        raise PasskeyError('Passkeys need a secure (https) connection.')
    return name, f'{scheme}://{host}'


def available(request: HttpRequest) -> bool:
    try:
        relying_party(request)
    except PasskeyError:
        return False
    return True


# -- challenges (single use, short lived, kept in the session) -----------------------------------


def _remember(request: HttpRequest, key: str, challenge: bytes, **extra: Any) -> None:
    request.session[key] = {'challenge': b64url_encode(challenge), 'at': time.time(), **extra}


def _recall(request: HttpRequest, key: str) -> dict[str, Any]:
    state = request.session.pop(key, None)  # popped: a challenge can be answered once
    if not isinstance(state, dict) or time.time() - float(state.get('at', 0)) > CHALLENGE_TTL:
        raise PasskeyError('That request expired. Start again.')
    return state


# -- registering a passkey -----------------------------------------------------------------------


def registration_options(request: HttpRequest, user: Any, name: str) -> dict[str, Any]:
    rp_id, _ = relying_party(request)
    if Passkey.objects.filter(user=user).count() >= MAX_PER_USER:
        raise PasskeyError(f'At most {MAX_PER_USER} passkeys per login. Remove one first.')
    challenge = webauthn.generate_challenge()
    _remember(request, _REGISTER, challenge, name=(name or 'Passkey').strip()[:64] or 'Passkey')
    from backend.config.branding import brand_name

    return {
        'rp': {'id': rp_id, 'name': brand_name()},
        'user': {
            'id': b64url_encode(str(user.pk).encode()),
            'name': user.email,
            'displayName': getattr(user, 'full_name', '') or user.email,
        },
        'challenge': b64url_encode(challenge),
        'pubKeyCredParams': _PUBKEY_PARAMS,
        'timeout': CHALLENGE_TTL * 1000,
        'attestation': 'none',
        'authenticatorSelection': {
            'residentKey': 'required',  # discoverable: it can sign in without typing an email
            'requireResidentKey': True,
            'userVerification': 'required',
        },
        'excludeCredentials': [
            {'type': 'public-key', 'id': p.credential_id}
            for p in Passkey.objects.filter(user=user).only('credential_id')
        ],
    }


@transaction.atomic
def finish_registration(request: HttpRequest, user: Any, payload: dict[str, Any]) -> Passkey:
    state = _recall(request, _REGISTER)
    rp_id, origin = relying_party(request)
    response = payload.get('response') or {}
    try:
        registration = webauthn.verify_registration(
            client_data_json=b64url_decode(str(response.get('clientDataJSON', ''))),
            attestation_object=b64url_decode(str(response.get('attestationObject', ''))),
            challenge=b64url_decode(state['challenge']),
            origin=origin,
            rp_id=rp_id,
        )
    except KeyError as exc:
        raise PasskeyError('The response was incomplete.') from exc
    transports = response.get('transports')
    try:
        return Passkey.objects.create(
            user=user,
            name=str(state.get('name', 'Passkey'))[:64],
            credential_id=b64url_encode(registration.credential_id),
            public_key=b64url_encode(registration.public_key),
            algorithm=registration.algorithm,
            sign_count=registration.sign_count,
            transports=[t for t in transports if isinstance(t, str)][:6]
            if isinstance(transports, list)
            else [],
            aaguid=registration.aaguid.hex(),
            backup_eligible=registration.backup_eligible,
            backed_up=registration.backed_up,
        )
    except IntegrityError as exc:
        raise PasskeyError('This passkey is already registered.') from exc


# -- signing in with a passkey -------------------------------------------------------------------


def authentication_options(request: HttpRequest, user: Any | None = None) -> dict[str, Any]:
    """Options for a sign-in; with ``user`` (second step) only that person's passkeys are offered."""
    rp_id, _ = relying_party(request)
    challenge = webauthn.generate_challenge()
    _remember(request, _SIGN_IN, challenge, user=str(user.pk) if user is not None else '')
    allow: list[dict[str, Any]] = []
    if user is not None:
        allow = [
            {'type': 'public-key', 'id': p.credential_id, 'transports': p.transports or []}
            for p in Passkey.objects.filter(user=user)
        ]
    return {
        'rpId': rp_id,
        'challenge': b64url_encode(challenge),
        'timeout': CHALLENGE_TTL * 1000,
        'userVerification': 'required',
        'allowCredentials': allow,
    }


def finish_authentication(
    request: HttpRequest, payload: dict[str, Any], *, expected_user: Any | None = None
) -> Passkey:
    """Verify an assertion and return the stored passkey it came from (its person is ``.user``)."""
    state = _recall(request, _SIGN_IN)
    rp_id, origin = relying_party(request)
    response = payload.get('response') or {}
    raw_id = str(payload.get('rawId') or payload.get('id') or '')
    passkey = Passkey.objects.select_related('user').filter(credential_id=raw_id).first()
    # One answer for every reason a sign-in can fail: which part was wrong is not for strangers.
    generic = PasskeyError('That passkey could not be used. Try again or sign in another way.')
    if passkey is None or not passkey.user.is_active:
        raise generic
    if expected_user is not None and passkey.user_id != expected_user.pk:
        raise generic
    if state.get('user') and state['user'] != str(passkey.user_id):
        raise generic
    handle = str(response.get('userHandle') or '')
    if handle:
        try:
            if b64url_decode(handle).decode() != str(passkey.user_id):
                raise generic
        except (WebAuthnError, UnicodeDecodeError) as exc:
            raise generic from exc
    try:
        assertion = webauthn.verify_assertion(
            client_data_json=b64url_decode(str(response.get('clientDataJSON', ''))),
            authenticator_data=b64url_decode(str(response.get('authenticatorData', ''))),
            signature=b64url_decode(str(response.get('signature', ''))),
            public_key=b64url_decode(passkey.public_key),
            challenge=b64url_decode(state['challenge']),
            origin=origin,
            rp_id=rp_id,
        )
    except WebAuthnError as exc:
        raise generic from exc
    if webauthn.counter_regressed(passkey.sign_count, assertion.sign_count):
        from backend.apps.core.platform.services.audit import AuditService

        AuditService.record(
            action='passkey_clone_suspected',
            user=passkey.user.email,
            detail=f'{passkey.name}: counter {assertion.sign_count} after {passkey.sign_count}',
            severity='warning',
        )
        raise generic
    passkey.sign_count = max(assertion.sign_count, passkey.sign_count)
    passkey.backed_up = assertion.backed_up
    passkey.last_used_at = timezone.now()
    passkey.save(update_fields=['sign_count', 'backed_up', 'last_used_at'])
    return passkey


# -- reading --------------------------------------------------------------------------------------


def has_passkey(user: Any) -> bool:
    return bool(user) and Passkey.objects.filter(user=user).exists()


def for_user(user: Any) -> list[Passkey]:
    return list(Passkey.objects.filter(user=user))


def parse_json(request: HttpRequest) -> dict[str, Any]:
    try:
        body = json.loads(request.body or b'{}')
    except ValueError as exc:
        raise PasskeyError('The request was not valid.') from exc
    if not isinstance(body, dict):
        raise PasskeyError('The request was not valid.')
    return body


def user_model() -> Any:
    return get_user_model()
