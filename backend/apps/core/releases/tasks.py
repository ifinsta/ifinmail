"""Background work for core.releases: keeping the device statistics bounded."""

from __future__ import annotations

from celery import shared_task

from backend.apps.core.releases.services import ReleaseService


@shared_task(name='releases.prune_checkins')
def prune_checkins() -> int:
    """Forget devices that have not asked for updates for half a year (daily)."""
    return ReleaseService.prune_checkins()
