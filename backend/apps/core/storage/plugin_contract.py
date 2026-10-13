"""The ``storage.objects`` capability: what a storage plugin may set, and its in-console target.

The values never reach a runtime file: the console itself reads them (``storage.config``), and the
secret stays encrypted in the database until the moment a request is signed.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from urllib.parse import urlsplit

from backend.apps.core.plugins.services import registry
from backend.apps.core.plugins.services import secrets as plugin_secrets
from backend.apps.core.plugins.services.registry import (
    AdapterTarget,
    Capability,
    CapabilityField,
    TargetKey,
)

from . import drivers
from .config import CAPABILITY, RETRIEVAL_MODES

TARGET = 'console.storage'
_BUCKET = re.compile(r'^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$')
_REGION = re.compile(r'^[A-Za-z0-9-]{1,40}$')
_KEY_ID = re.compile(r'^[A-Za-z0-9+/=_.-]{3,128}$')
_PREFIX = re.compile(r'^[A-Za-z0-9!_.*\'()/-]{0,200}$')


def _driver(value: str) -> str | None:
    return None if value in drivers.names() else f'must be one of {", ".join(drivers.names())}'


def _url(value: str) -> str | None:
    parts = urlsplit(value)
    if parts.scheme not in ('http', 'https') or not parts.hostname:
        return 'must be an http(s) URL such as https://s3.eu-central-1.amazonaws.com'
    if parts.username or parts.password or parts.query or parts.fragment or len(value) > 300:
        return 'must be a plain URL (no credentials, query or fragment)'
    return None


def _bucket(value: str) -> str | None:
    return (
        None
        if _BUCKET.match(value)
        else 'must be a bucket name (3-63 lower-case letters, digits, dots, dashes)'
    )


def _region(value: str) -> str | None:
    return None if _REGION.match(value) else 'must be a region name such as us-east-1'


def _key_id(value: str) -> str | None:
    return None if _KEY_ID.match(value) else 'must be an access key id'


def _encrypted(value: str) -> str | None:
    return None if plugin_secrets.is_encrypted(value) else 'must be stored encrypted'


def _prefix(value: str) -> str | None:
    ok = _PREFIX.match(value) and '..' not in value and not value.startswith('/')
    return None if ok else 'must be a simple path such as ifinmail/mail-example-com'


def _choice(*allowed: str) -> Callable[[str], str | None]:
    def check(value: str) -> str | None:
        return None if value in allowed else f'must be one of {", ".join(allowed)}'

    return check


def _flag(value: str) -> str | None:
    return None if value in ('yes', 'no') else 'must be yes or no'


def _seconds(value: str) -> str | None:
    ok = value.isdigit() and 30 <= int(value) <= 86400
    return None if ok else 'must be a number of seconds from 30 to 86400'


_FIELDS = {
    'driver': (_driver, 'Which storage driver implements the contract (s3).'),
    'endpoint': (_url, 'The service endpoint, e.g. https://s3.eu-central-1.amazonaws.com.'),
    'region': (_region, 'Signing region; us-east-1 when the provider does not care.'),
    'bucket': (_bucket, 'The bucket this server writes to.'),
    'prefix': (_prefix, 'A folder inside the bucket for this server.'),
    'access_key': (_key_id, 'Access key id of a key that may only use this bucket.'),
    'secret_key': (_encrypted, 'Secret access key, stored encrypted.'),
    'addressing': (_choice('path', 'virtual'), 'Path-style or virtual-host-style URLs.'),
    'retrieval': (_choice(*RETRIEVAL_MODES), 'How clients fetch media: redirect, public or proxy.'),
    'public_base_url': (_url, 'Public or CDN base URL for "public" retrieval.'),
    'url_seconds': (_seconds, 'How long a pre-signed link stays valid.'),
    'media': (_flag, 'Keep uploaded media (branding, attachments) in this store.'),
    'backups': (_flag, 'Send encrypted backups to this store.'),
}


class StorageTarget(AdapterTarget):
    """Read in the console; nothing for a container to apply."""

    key = TARGET
    service = 'api'
    in_process = True
    keys = {name: TargetKey(check, text) for name, (check, text) in _FIELDS.items()}


class StorageCapability(Capability):
    key = CAPABILITY
    title = 'External storage'
    description = (
        'Where the console keeps files it manages (media, encrypted backups): any store that '
        'implements the storage contract, chosen by driver.'
    )
    fields = {
        name: CapabilityField(
            check,
            text,
            (TARGET, name),
            secret=name == 'secret_key',
            normalize=(lambda v: v.strip().rstrip('/'))
            if name in ('endpoint', 'public_base_url')
            else (lambda v: v.strip().strip('/'))
            if name == 'prefix'
            else None,
        )
        for name, (check, text) in _FIELDS.items()
    }


def register() -> None:
    registry.register_target(StorageTarget())
    registry.register_capability(StorageCapability())
