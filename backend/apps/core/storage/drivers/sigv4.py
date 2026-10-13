"""AWS Signature Version 4 for S3, with the standard library only.

Two forms: the ``Authorization`` header (every request the console makes) and the query string
(pre-signed URLs a browser or mail client can follow for a few minutes). The algorithm is
documented by AWS and implemented by every S3-compatible service; the tests check it against
AWS's own published examples.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from datetime import UTC, datetime
from urllib.parse import quote

ALGORITHM = 'AWS4-HMAC-SHA256'
UNSIGNED = 'UNSIGNED-PAYLOAD'
EMPTY_SHA256 = hashlib.sha256(b'').hexdigest()


def _hmac(key: bytes, text: str) -> bytes:
    return hmac.new(key, text.encode('utf-8'), hashlib.sha256).digest()


def signing_key(secret: str, date: str, region: str, service: str = 's3') -> bytes:
    key = _hmac(('AWS4' + secret).encode('utf-8'), date)
    key = _hmac(key, region)
    key = _hmac(key, service)
    return _hmac(key, 'aws4_request')


def uri_encode(text: str, *, keep_slash: bool) -> str:
    """RFC 3986 encoding as SigV4 wants it (only unreserved characters stay as they are)."""
    return quote(text, safe='/~' if keep_slash else '~')


def canonical_query(params: Mapping[str, str]) -> str:
    pairs = sorted(
        (uri_encode(k, keep_slash=False), uri_encode(v, keep_slash=False))
        for k, v in params.items()
    )
    return '&'.join(f'{k}={v}' for k, v in pairs)


def _canonical_headers(headers: Mapping[str, str]) -> tuple[str, str]:
    items = sorted((k.lower().strip(), ' '.join(str(v).split())) for k, v in headers.items())
    canonical = ''.join(f'{k}:{v}\n' for k, v in items)
    return canonical, ';'.join(k for k, _ in items)


def _string_to_sign(amz_date: str, scope: str, canonical_request: str) -> str:
    return '\n'.join(
        [ALGORITHM, amz_date, scope, hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()]
    )


def stamp(now: datetime | None = None) -> tuple[str, str]:
    """``(amz_date, date)`` such as ``('20130524T000000Z', '20130524')``."""
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    return moment.strftime('%Y%m%dT%H%M%SZ'), moment.strftime('%Y%m%d')


def sign_headers(
    *,
    method: str,
    path: str,
    query: Mapping[str, str],
    headers: Mapping[str, str],
    payload_sha256: str,
    access_key: str,
    secret_key: str,
    region: str,
    now: datetime | None = None,
    service: str = 's3',
) -> dict[str, str]:
    """The headers to send: ``headers`` plus x-amz-date, x-amz-content-sha256 and Authorization.

    ``headers`` must include ``host``. ``path`` is the raw (unencoded) path, starting with '/'.
    """
    amz_date, date = stamp(now)
    signed = {**headers, 'x-amz-date': amz_date, 'x-amz-content-sha256': payload_sha256}
    canonical_headers, signed_names = _canonical_headers(signed)
    canonical_request = '\n'.join(
        [
            method,
            uri_encode(path, keep_slash=True),
            canonical_query(query),
            canonical_headers,
            signed_names,
            payload_sha256,
        ]
    )
    scope = f'{date}/{region}/{service}/aws4_request'
    signature = hmac.new(
        signing_key(secret_key, date, region, service),
        _string_to_sign(amz_date, scope, canonical_request).encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()
    signed['Authorization'] = (
        f'{ALGORITHM} Credential={access_key}/{scope}, SignedHeaders={signed_names}, '
        f'Signature={signature}'
    )
    return signed


def presign(
    *,
    method: str,
    host: str,
    path: str,
    access_key: str,
    secret_key: str,
    region: str,
    expires: int,
    query: Mapping[str, str] | None = None,
    now: datetime | None = None,
    service: str = 's3',
) -> str:
    """The query string (without '?') that authorises ``method path`` for ``expires`` seconds."""
    amz_date, date = stamp(now)
    scope = f'{date}/{region}/{service}/aws4_request'
    params = {
        **(query or {}),
        'X-Amz-Algorithm': ALGORITHM,
        'X-Amz-Credential': f'{access_key}/{scope}',
        'X-Amz-Date': amz_date,
        'X-Amz-Expires': str(int(expires)),
        'X-Amz-SignedHeaders': 'host',
    }
    canonical_request = '\n'.join(
        [
            method,
            uri_encode(path, keep_slash=True),
            canonical_query(params),
            f'host:{host}\n',
            'host',
            UNSIGNED,
        ]
    )
    signature = hmac.new(
        signing_key(secret_key, date, region, service),
        _string_to_sign(amz_date, scope, canonical_request).encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()
    return canonical_query(params) + f'&X-Amz-Signature={signature}'
