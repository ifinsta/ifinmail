"""Which store holds which files: read from the ``storage.objects`` capability a plugin configures.

With no plugin (or the plugin off) every purpose uses the local disk, exactly as before. When the
Object storage plugin routes a purpose to an external store, that purpose is read and written
there. Stores are built once per distinct configuration and reused.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings

from . import drivers
from .contract import ObjectStore, StorageRejectedError

CAPABILITY = 'storage.objects'
PURPOSES = ('media', 'backups')
RETRIEVAL_MODES = ('redirect', 'public', 'proxy')
DEFAULT_URL_SECONDS = 300

_lock = threading.Lock()
_cache: dict[str, ObjectStore] = {}


@dataclass(frozen=True)
class StoreSettings:
    driver: str
    values: dict[str, str] = field(repr=False)
    purposes: frozenset[str] = frozenset()
    retrieval: str = 'redirect'
    public_base_url: str = ''
    url_seconds: int = DEFAULT_URL_SECONDS

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(self.values, sort_keys=True).encode()).hexdigest()


def _truthy(value: str | None) -> bool:
    return str(value or '').strip().lower() in ('1', 'true', 'yes', 'on')


def current() -> StoreSettings | None:
    """The external store the plugin configured, or ``None`` (everything stays on the disk)."""
    try:
        from backend.apps.core.plugins.services import InstallationService
        from backend.apps.core.plugins.services import secrets as plugin_secrets

        values = dict(InstallationService.capability_values(CAPABILITY))
    except Exception:  # no database yet (first boot, migrations): the disk is always safe
        return None
    driver = (values.get('driver') or '').strip()
    if not driver or driver == 'local' or not values.get('endpoint'):
        return None
    purposes = frozenset(p for p in PURPOSES if _truthy(values.get(p)))
    if not purposes:
        return None
    secret = values.get('secret_key', '')
    if secret:
        try:
            values['secret_key'] = plugin_secrets.decrypt(secret)
        except ValueError:
            values['secret_key'] = ''
    try:
        seconds = int(values.get('url_seconds') or DEFAULT_URL_SECONDS)
    except ValueError:
        seconds = DEFAULT_URL_SECONDS
    retrieval = values.get('retrieval', 'redirect')
    return StoreSettings(
        driver=driver,
        values=values,
        purposes=purposes,
        retrieval=retrieval if retrieval in RETRIEVAL_MODES else 'redirect',
        public_base_url=(values.get('public_base_url') or '').rstrip('/'),
        url_seconds=max(30, min(seconds, 24 * 3600)),
    )


def local_store() -> ObjectStore:
    return drivers.build('local', {'root': str(settings.MEDIA_ROOT)})


def external(purpose: str) -> StoreSettings | None:
    """The external store's settings when ``purpose`` is routed to one."""
    chosen = current()
    return chosen if chosen is not None and purpose in chosen.purposes else None


def store_for(purpose: str) -> ObjectStore:
    """The store that holds ``purpose`` (``media`` or ``backups``)."""
    if purpose not in PURPOSES:
        raise StorageRejectedError(f'Unknown storage purpose "{purpose}".')
    chosen = external(purpose)
    if chosen is None:
        if purpose == 'backups':
            raise StorageRejectedError('No external store is set up for backups.')
        return local_store()
    key = f'{chosen.driver}:{chosen.fingerprint}'
    with _lock:
        store = _cache.get(key)
        if store is None:
            store = drivers.build(chosen.driver, chosen.values)
            _cache.clear()  # one live configuration at a time
            _cache[key] = store
    return store


def describe() -> dict[str, Any]:
    """For pages and health: where each purpose lives (never a secret)."""
    chosen = current()
    out: dict[str, Any] = {'configured': chosen is not None, 'purposes': {}}
    for purpose in PURPOSES:
        if chosen is not None and purpose in chosen.purposes:
            out['purposes'][purpose] = {
                'driver': chosen.driver,
                'where': f'{chosen.values.get("endpoint", "")} · {chosen.values.get("bucket", "")}'
                + (f'/{chosen.values.get("prefix")}' if chosen.values.get('prefix') else ''),
                'retrieval': chosen.retrieval if purpose == 'media' else '',
            }
        else:
            out['purposes'][purpose] = {
                'driver': 'local',
                'where': 'this server’s disk' if purpose == 'media' else 'this server’s disk only',
                'retrieval': 'served by the web server' if purpose == 'media' else '',
            }
    return out
