"""The external store's health: a periodic write/read/delete probe, remembered for System health.

Only an external store is probed (the disk is covered by the disk checks). A change of state (it
started failing, it recovered) is audited once; a store that keeps failing is not re-audited every
half hour.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from . import config

SETTING = 'storage.last_probe'


def last() -> dict[str, Any] | None:
    from backend.apps.core.services import SystemSettings

    value = SystemSettings.get(SETTING, None)
    return value if isinstance(value, dict) else None


def run_probe() -> dict[str, Any]:
    from backend.apps.core.platform.services.audit import AuditService
    from backend.apps.core.services import SystemSettings

    chosen = config.current()
    if chosen is None:
        SystemSettings.set(SETTING, None)
        return {'configured': False}
    purpose = sorted(chosen.purposes)[0]
    try:
        result = config.store_for(purpose).probe()
        ok, detail, ms, driver = result.ok, result.detail, result.milliseconds, result.driver
    except Exception as exc:  # a store that cannot even be built is a failure, not a crash
        ok, detail, ms, driver = False, str(exc)[:300], 0, chosen.driver
    previous = last() or {}
    record = {
        'at': datetime.now(UTC).isoformat(timespec='seconds'),
        'ok': ok,
        'detail': detail,
        'milliseconds': ms,
        'driver': driver,
        'purposes': sorted(chosen.purposes),
    }
    SystemSettings.set(SETTING, record)
    if previous.get('ok') is not ok:
        AuditService.record(
            action='storage_probe_ok' if ok else 'storage_probe_failed',
            user='system',
            detail=detail[:200],
            severity='info' if ok else 'warning',
        )
    return record
