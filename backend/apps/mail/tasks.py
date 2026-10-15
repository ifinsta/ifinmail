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


@shared_task(name='mail.purge_sandbox')
def purge_sandbox() -> int:
    """Drop captured sandbox mail older than the Developer sandbox plugin's retention (daily)."""
    from .services import sandbox

    return sandbox.purge()


@shared_task(name='mail.deliver_webhook')
def deliver_webhook(delivery_id: str) -> bool:
    """Deliver one webhook event now (queued when the event happens)."""
    from .services import webhooks

    return webhooks.deliver(delivery_id)


@shared_task(name='mail.sweep_webhooks')
def sweep_webhooks() -> int:
    """Retry webhook deliveries that are due, and forget old ones (every minute)."""
    from .services import webhooks

    return webhooks.sweep()


@shared_task(name='mail.scan_delivery_events')
def scan_delivery_events() -> int:
    """Turn new Postfix log lines about API mail into delivery events (every minute)."""
    from .services import delivery_events

    try:
        return delivery_events.scan()
    except Exception:
        logging.getLogger('backend').warning('Delivery events scan failed', exc_info=True)
        return 0


@shared_task(name='mail.expire_agent_inboxes')
def expire_agent_inboxes() -> int:
    """Erase and remove agent inboxes whose time is up (every five minutes)."""
    from .services import agent_inboxes

    return agent_inboxes.expire()


@shared_task(name='mail.scan_inbox_events')
def scan_inbox_events() -> int:
    """New mail in watched mailboxes becomes message.received events (every 30 seconds)."""
    from .services import inbox_events

    try:
        return inbox_events.scan()
    except Exception:
        logging.getLogger('backend').warning('Inbox webhooks scan failed', exc_info=True)
        return 0


@shared_task(name='mail.expire_approvals')
def expire_approvals() -> int:
    """Held messages nobody decided on in time expire (every five minutes)."""
    from .services import approvals

    return approvals.expire()
