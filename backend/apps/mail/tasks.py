"""Mail jobs: keep the Postfix overrides file on the shared volume current."""

from __future__ import annotations

from celery import shared_task

from .services.postfix_runtime import PostfixRuntime


@shared_task(name='mail.apply_postfix_overrides')
def apply_postfix_overrides() -> int:
    """Re-publish the outbound settings (covers a freshly created runtime volume)."""
    return len(PostfixRuntime.apply().splitlines())
