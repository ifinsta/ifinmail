"""Mail jobs: keep the Postfix overrides file current; contain suspected compromised mailboxes."""

from __future__ import annotations

import logging

from celery import shared_task

from .services.postfix_runtime import PostfixRuntime


@shared_task(name='mail.apply_postfix_overrides')
def apply_postfix_overrides() -> int:
    """Re-publish the outbound settings (covers a freshly created runtime volume)."""
    return len(PostfixRuntime.apply().splitlines())


@shared_task(name='mail.check_outbound_containment')
def check_outbound_containment() -> dict[str, list[str]]:
    """Compare each mailbox's hourly sending with the Outbound policy thresholds (every minute)."""
    from .services import containment

    try:
        return containment.evaluate()
    except Exception:  # Redis or the database briefly unavailable: try again next minute
        logging.getLogger('backend').warning('Outbound containment check failed', exc_info=True)
        return {'paused': [], 'alerted': []}
