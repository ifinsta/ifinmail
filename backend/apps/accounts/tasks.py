"""accounts — Celery tasks."""

from __future__ import annotations

from celery import shared_task


@shared_task(name='accounts.publish_directory')
def publish_directory() -> dict[str, object]:
    """Write the contact directory to the runtime volume (cheap when nothing changed)."""
    from backend.apps.accounts.services import directory

    return directory.publish()
