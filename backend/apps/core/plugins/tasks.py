"""Plugin background job: reconcile desired state with the files the containers apply."""

from __future__ import annotations

from celery import shared_task

from backend.apps.core.plugins.services import InstallationService


@shared_task(name='plugins.reconcile')
def reconcile() -> dict[str, object]:
    """Finish interrupted operations and republish every adapter target (writes only on drift)."""
    return InstallationService.reconcile()
