"""Background work for core.storage: proving the external store still works."""

from __future__ import annotations

from typing import Any

from celery import shared_task

from backend.apps.core.storage import health


@shared_task(name='storage.probe')
def probe() -> dict[str, Any]:
    """Write, read back and remove a test object in every external store (every 30 minutes)."""
    return health.run_probe()
