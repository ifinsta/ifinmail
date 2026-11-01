"""Mail jobs: keep the Postfix overrides file current; contain suspected compromised mailboxes."""

from __future__ import annotations

import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

from .services.postfix_runtime import PostfixRuntime

logger = logging.getLogger('backend')

# A scan takes seconds. Mail and log lines are written by strangers, so one that makes a scan hang
# must not hold a worker: the soft limit raises SoftTimeLimitExceeded inside the task (the scan
# stops cleanly and the next run picks up where it left off); the hard limit kills the worker
# process if the task is still running, because something swallowed the soft limit (an
# ``except Exception`` does) or is stuck in a C call that never lets Python handle signals. Both
# are well above a real run and a few times the 30 and 60 second schedules. With
# CELERY_TASK_ACKS_LATE a task stopped by its hard limit is failed and acknowledged, not
# redelivered (checked against a real worker), so a poisoned run cannot loop forever.
SCAN_SOFT_TIME_LIMIT = 90
SCAN_TIME_LIMIT = 120


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
    """Deliver one webhook event now. Nothing queues these any more (see ``deliver_webhooks``);
    it stays so that messages already on the queue when a worker is updated still run."""
    from .services import webhooks

    return webhooks.deliver(delivery_id)


# A chunk of deliveries to one endpoint (webhooks.deliver_batch): it stops taking new deliveries
# after BATCH_BUDGET_SECONDS (15) and queues the rest, so a task is at most that plus one attempt
# (10 s timeout, and a DNS check) long. The limits sit above that, with room to spare, and a task
# that is stuck beyond them is stopped so it cannot keep a worker; a test pins the arithmetic.
WEBHOOK_BATCH_SOFT_TIME_LIMIT = 60
WEBHOOK_BATCH_TIME_LIMIT = 80


@shared_task(
    name='mail.deliver_webhooks',
    soft_time_limit=WEBHOOK_BATCH_SOFT_TIME_LIMIT,
    time_limit=WEBHOOK_BATCH_TIME_LIMIT,
)
def deliver_webhooks(delivery_ids: list[str]) -> int:
    """Deliver a chunk of events to one endpoint, one after another (queued when they happen)."""
    from .services import webhooks

    return webhooks.deliver_batch(delivery_ids)


@shared_task(name='mail.sweep_webhooks')
def sweep_webhooks() -> int:
    """Retry webhook deliveries that are due, and forget old ones (every minute)."""
    from .services import webhooks

    return webhooks.sweep()


@shared_task(
    name='mail.scan_delivery_events',
    soft_time_limit=SCAN_SOFT_TIME_LIMIT,
    time_limit=SCAN_TIME_LIMIT,
)
def scan_delivery_events() -> int:
    """Turn new Postfix log lines about API mail into delivery events (every minute)."""
    from .services import delivery_events

    try:
        return delivery_events.scan()
    except SoftTimeLimitExceeded:
        logger.warning('Delivery events scan hit its time limit; the rest follows on the next run')
        return 0
    except Exception:
        logger.warning('Delivery events scan failed', exc_info=True)
        return 0


@shared_task(name='mail.expire_agent_inboxes')
def expire_agent_inboxes() -> int:
    """Erase and remove agent inboxes whose time is up (every five minutes)."""
    from .services import agent_inboxes

    return agent_inboxes.expire()


@shared_task(
    name='mail.scan_inbox_events',
    soft_time_limit=SCAN_SOFT_TIME_LIMIT,
    time_limit=SCAN_TIME_LIMIT,
)
def scan_inbox_events() -> int:
    """New mail in watched mailboxes becomes message.received events (every 30 seconds)."""
    from .services import inbox_events

    try:
        return inbox_events.scan()
    except SoftTimeLimitExceeded:
        logger.warning('Inbox webhooks scan hit its time limit; the rest follows on the next run')
        return 0
    except Exception:
        logger.warning('Inbox webhooks scan failed', exc_info=True)
        return 0


@shared_task(name='mail.expire_approvals')
def expire_approvals() -> int:
    """Held messages nobody decided on in time expire (every five minutes)."""
    from .services import approvals

    return approvals.expire()
