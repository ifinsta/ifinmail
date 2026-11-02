"""Sends campaigns at the pace the Marketing plugin allows (``mail.run_campaigns``, every minute).

A campaign is created in one request and sent over time. Each run:

* works out its budget: the plugin's emails per minute (less what any run already sent in this
  clock minute), capped by what is left of today's ceiling.
  With warm-up on the ceiling starts low and grows by half each day, because a sender that has
  never mailed anyone and suddenly mails thousands is treated as a spammer;
* starts the scheduled campaigns whose time has come (one more than six hours late is held
  instead: see ``marketing.start_due``);
* shares the budget between the campaigns that are sending, so a big one does not starve a small
  one;
* claims each recipient with one conditional UPDATE right before its email, so two runs that
  overlap never send the same person twice and a worker that dies leaves at most one recipient
  in doubt, and checks the opt-out and suppression lists again (somebody can unsubscribe between
  creation and sending);
* stops a campaign, rather than sending on, when its sender has been paused by containment, when
  its key has been paused by the bounce guard, or when its own bounce rate is too high.

Campaign mail is not counted against the per-key daily cap or the per-minute and per-day limits
of transactional mail, and it does not feed containment's hourly thresholds, which would pause a
mailbox for sending a newsletter. It has the limits above instead.

A recipient whose send was cut short (the worker died while it was in flight) is marked failed
with "interrupted" and not retried: a duplicate marketing email is worse than a rare miss, and
the status says exactly which ones to look at. A relay that refuses the connection is different:
nothing was sent, so the recipients go back to pending and the next run tries again.
"""

from __future__ import annotations

import contextlib
import html as html_lib
import logging
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.utils import make_msgid
from smtplib import SMTPDataError, SMTPException, SMTPRecipientsRefused, SMTPSenderRefused

from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives, get_connection
from django.db.models import Min
from django.utils import timezone
from django.utils.html import strip_tags

from backend.apps.domains.models import Domain
from backend.apps.mail.models import Campaign, CampaignRecipient
from backend.apps.mail.services import containment, delivery_events, marketing, tracking

logger = logging.getLogger('backend')

SMTP_TIMEOUT_SECONDS = 10
STALE_CLAIM = timedelta(minutes=2)  # a claim older than this belongs to a run that died
# (one email takes seconds: the relay timeout is 10 s)
LOCK_KEY = 'marketing:run'
LOCK_SECONDS = 100  # longer than a run may last (the task's soft limit is 90 s)
ACTIVE_SECONDS = 8 * 24 * 3600  # how long the delivery log is followed after the last send
WARMUP_GROWTH = 1.5  # the daily ceiling grows by half each day
MAX_PASSES = 2000  # a run's loops over the campaigns: skipped recipients cost no budget
FAIL_STREAK_PAUSE = 20  # this many failed emails in a row pause the campaign (see _tripped)


@dataclass
class RunResult:
    sent: int = 0
    failed: int = 0
    skipped: int = 0
    completed: int = 0
    paused: int = 0
    started: int = 0  # scheduled campaigns whose time came
    note: str = ''  # why a run did nothing, when it did nothing


# ------------------------------------------------------------------------------ the budget


def _midnight(now: datetime) -> datetime:
    return timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)


def sent_today(now: datetime) -> int:
    return CampaignRecipient.objects.filter(
        status=CampaignRecipient.SENT, sent_at__gte=_midnight(now)
    ).count()


def sent_this_minute(now: datetime) -> int:
    """Emails sent in the current clock minute, by any run.

    The pace is per minute, not per run: a second run in the same minute (a manual trigger, a
    delayed schedule tick) must find the minute's budget already spent, or the pace is exceeded.
    """
    return CampaignRecipient.objects.filter(
        status=CampaignRecipient.SENT, sent_at__gte=now.replace(second=0, microsecond=0)
    ).count()


def ceiling_today(cfg: marketing.MarketingSettings, now: datetime) -> int:
    """Emails allowed today: the daily ceiling, or less while warming up."""
    if not cfg.warmup:
        return cfg.daily_ceiling
    first = CampaignRecipient.objects.filter(status=CampaignRecipient.SENT).aggregate(
        first=Min('sent_at')
    )['first']
    days = 0
    if first is not None:
        days = max((timezone.localdate(now) - timezone.localdate(first)).days, 0)
    return min(cfg.daily_ceiling, int(cfg.warmup_start * WARMUP_GROWTH**days))


# ------------------------------------------------------------------------------ a run


def run(now: datetime | None = None) -> RunResult:
    now = now or timezone.now()
    result = RunResult()
    cfg = marketing.settings()
    if not cfg.enabled or not cfg.postal_address:
        result.note = 'marketing is off or has no postal address'
        return result
    try:
        if not cache.add(LOCK_KEY, 1, LOCK_SECONDS):
            result.note = 'another run is in progress'
            return result
    except Exception:
        logger.warning('Campaign runner: the cache is unavailable, not sending')
        result.note = 'the cache is unavailable'
        return result
    try:
        _run(cfg, now, result)
    finally:
        try:
            cache.delete(LOCK_KEY)
        except Exception:
            logger.warning('Campaign runner: could not release its lock; it expires on its own')
    return result


def _run(cfg: marketing.MarketingSettings, now: datetime, result: RunResult) -> None:
    CampaignRecipient.objects.filter(
        status=CampaignRecipient.SENDING, claimed_at__lt=now - STALE_CLAIM
    ).update(
        status=CampaignRecipient.FAILED,
        detail='interrupted: may or may not have been sent',
        claim_token='',
    )
    started, held = marketing.start_due(now)
    result.started += started
    result.paused += held
    active = list(Campaign.objects.filter(status=Campaign.SENDING).order_by('created_at'))
    if not active:
        result.note = 'nothing is sending'
        return
    runnable = [campaign for campaign in active if not _stopped(campaign, result)]
    if not runnable:
        return
    room = ceiling_today(cfg, now) - sent_today(now)
    if room <= 0:
        result.note = "today's ceiling is reached"
        return
    budget = min(cfg.pace_per_minute - sent_this_minute(now), room)
    if budget <= 0:
        result.note = "this minute's pace is used up"
        return

    connection = get_connection(fail_silently=False, timeout=SMTP_TIMEOUT_SECONDS)
    try:
        connection.open()
    except (SMTPException, OSError) as exc:
        logger.warning('Campaign runner: the relay did not accept a connection: %s', exc)
        result.note = 'the relay did not accept a connection'
        return
    try:
        try:
            cache.set(delivery_events.MARKETING_ACTIVE, 1, ACTIVE_SECONDS)
        except Exception:
            logger.warning('Campaign runner: could not flag marketing as active')
        share = max(1, math.ceil(budget / len(runnable)))
        for _ in range(MAX_PASSES):
            if budget <= 0 or not runnable:
                break
            for campaign in list(runnable):
                done, more = _send_batch(campaign, min(share, budget), connection, cfg, now, result)
                budget -= done
                if not more:
                    runnable.remove(campaign)
                if budget <= 0:
                    break
    finally:
        with contextlib.suppress(Exception):  # the connection may already be gone
            connection.close()


def _stopped(campaign: Campaign, result: RunResult) -> bool:
    """Pause the campaign and say so when it must not go on; True when it was paused."""
    reason = ''
    sender = campaign.sender
    if sender in containment.paused():
        reason = f'Sending is paused for {sender}. An administrator must resume it first.'
    elif not Domain.objects.filter(name=sender.rpartition('@')[2]).exists():
        reason = f'{sender.rpartition("@")[2]} is no longer a domain on this server.'
    else:
        from backend.apps.mail.services import compliance

        if compliance.settings().enabled and campaign.key_prefix:
            stopped = compliance.paused(campaign.key_prefix)
            if stopped:
                reason = (
                    f'The key is paused: {stopped["rate"]}% of its {stopped["total"]} messages '
                    'today bounced. Clean the list, then ask an administrator to resume it.'
                )
        if not reason:
            reason = marketing.over_bounce_limit(campaign)
    if not reason:
        return False
    if marketing.pause(campaign, reason):
        result.paused += 1
        logger.warning('Campaign %s paused: %s', campaign.pk, reason)
    return True


# ------------------------------------------------------------------------------ a batch


def _send_batch(
    campaign: Campaign,
    take: int,
    connection,  # noqa: ANN001  (the mail backend's connection)
    cfg: marketing.MarketingSettings,
    now: datetime,
    result: RunResult,
) -> tuple[int, bool]:
    """Handle up to ``take`` pending recipients. Returns ``(attempted, can_continue)``.

    ``attempted`` is how many emails went to the relay, accepted or refused: that is what the
    pace limits, so a relay that refuses everything is not hammered. Recipients skipped for the
    lists or for missing data never reach it and cost nothing. ``can_continue`` is False when the
    campaign has nothing left, the relay failed, or the campaign was paused.
    """
    rows = list(
        CampaignRecipient.objects.filter(
            campaign=campaign, status=CampaignRecipient.PENDING
        ).order_by('pk')[:take]
    )
    if not rows:
        _finish_if_done(campaign, now, result)
        return 0, False
    token = str(uuid.uuid4())
    domain = campaign.sender.rpartition('@')[2]
    links = tracking.link_ids(campaign) if campaign.track_clicks else None
    refused = marketing.skip_reasons(domain, [row.address for row in rows])

    attempted = 0  # emails handed to the relay, accepted or refused
    stop = False
    streak = 0  # failed emails in a row, in this batch
    last_failure = ''
    remembered: list[tuple[str, str, str, str]] = []
    try:
        for row in rows:
            # One recipient is claimed at a time, right before its email, so that a worker that
            # dies leaves at most one recipient in doubt (the one in flight) and every other row
            # still pending for the next run. Claiming the batch up front left all of it in doubt.
            if not _claim(row, token):
                continue  # another run, or a pause, got there first
            if row.address in refused:
                _mark(row, CampaignRecipient.SKIPPED, refused[row.address])
                result.skipped += 1
                continue
            try:
                composed = marketing.compose(
                    campaign,
                    row.address,
                    row.merge,
                    cfg.postal_address,
                    tracking.Tracking(row.pk, campaign.track_opens, links)
                    if campaign.track_opens or links
                    else None,
                )
            except marketing.MissingValue as exc:
                _mark(row, CampaignRecipient.FAILED, f'missing: {exc.name}')
                result.failed += 1
                continue  # the person's data, not the relay: it does not count towards a streak
            message_id = make_msgid(domain=domain)
            mail = _build(campaign, row.address, composed, message_id, connection)
            attempted += 1
            try:
                mail.send()
            except (SMTPRecipientsRefused, SMTPSenderRefused) as exc:
                last_failure = f'refused: {str(exc)[:250]}'
                _mark(row, CampaignRecipient.FAILED, last_failure)
                result.failed += 1
                streak += 1
                if streak >= FAIL_STREAK_PAUSE:
                    break
                continue
            except SMTPDataError as exc:
                if 500 <= exc.smtp_code < 600:
                    last_failure = f'refused: {exc.smtp_code} {exc.smtp_error!r}'[:250]
                    _mark(row, CampaignRecipient.FAILED, last_failure)
                    result.failed += 1
                    streak += 1
                    if streak >= FAIL_STREAK_PAUSE:
                        break
                    continue
                stop = True
            except (SMTPException, OSError) as exc:
                logger.warning('Campaign runner: the relay failed mid-run: %s', exc)
                stop = True
            if stop:
                # Nothing was sent for this one: it goes back to pending with all the others.
                CampaignRecipient.objects.filter(pk=row.pk, claim_token=token).update(
                    status=CampaignRecipient.PENDING, claim_token='', claimed_at=None
                )
                attempted -= 1
                break
            CampaignRecipient.objects.filter(pk=row.pk).update(
                status=CampaignRecipient.SENT,
                message_id=message_id.strip('<>'),
                sent_at=timezone.now(),
                claim_token='',
            )
            remembered.append((message_id, campaign.key_prefix, campaign.sender, str(campaign.pk)))
            streak = 0
            result.sent += 1
    finally:
        try:
            delivery_events.remember_many(remembered)
        except Exception:  # events are a convenience; the mail is already sent
            logger.warning('Campaign runner: could not record delivery events', exc_info=True)
    reason = '' if stop else _tripped(campaign, streak, last_failure)
    if reason:
        if marketing.pause(campaign, reason):
            result.paused += 1
            logger.warning('Campaign %s paused: %s', campaign.pk, reason)
        return attempted, False
    if not stop:
        _finish_if_done(campaign, now, result)
    return attempted, not stop


def _tripped(campaign: Campaign, streak: int, last_failure: str) -> str:
    """A reason to pause when the mail server has refused ``FAIL_STREAK_PAUSE`` emails in a row.

    A relay that refuses everything (a misconfiguration, a blocklisting, a list full of dead
    domains) would otherwise take the whole list through to "failed" in seconds. Paused, the rest
    stays pending: the owner looks, fixes it, and resumes. The streak also counts across runs, for
    a pace so low that one run never sees that many.
    """
    if streak < FAIL_STREAK_PAUSE:
        recent = list(
            CampaignRecipient.objects.filter(
                campaign=campaign,
                status__in=[CampaignRecipient.SENT, CampaignRecipient.FAILED],
            )
            .order_by('-pk')
            .values_list('status', 'detail')[:FAIL_STREAK_PAUSE]
        )
        # Only what the relay refused counts: a person skipped for missing data, or an email cut
        # short by a dead worker, says nothing about the relay.
        refused = all(
            status == CampaignRecipient.FAILED and detail.startswith('refused')
            for status, detail in recent
        )
        if len(recent) < FAIL_STREAK_PAUSE or not refused:
            return ''
        last_failure = recent[0][1]
    return (
        f'The mail server refused {FAIL_STREAK_PAUSE} emails in a row ({last_failure}). '
        'Check the server and the list, then resume the campaign or cancel it.'
    )


def _build(
    campaign: Campaign,
    recipient: str,
    composed: marketing.Composed,
    message_id: str,
    connection,  # noqa: ANN001
) -> EmailMultiAlternatives:
    body = composed.text or html_lib.unescape(strip_tags(composed.html))
    mail = EmailMultiAlternatives(
        subject=composed.subject,
        body=body,
        from_email=campaign.sender,
        to=[recipient],
        reply_to=[campaign.reply_to] if campaign.reply_to else None,
        headers={
            'Message-ID': message_id,
            'X-Mailer': 'ifinmail-marketing',
            'Precedence': 'bulk',
            'List-Unsubscribe': f'<{composed.unsubscribe_url}>',
            'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click',
        },
        connection=connection,
    )
    if composed.html.strip():
        mail.attach_alternative(composed.html, 'text/html')
    return mail


def _claim(row: CampaignRecipient, token: str) -> bool:
    """Take one pending recipient for sending, or False when someone else has it."""
    return bool(
        CampaignRecipient.objects.filter(pk=row.pk, status=CampaignRecipient.PENDING).update(
            status=CampaignRecipient.SENDING, claim_token=token, claimed_at=timezone.now()
        )
    )


def _mark(row: CampaignRecipient, status: str, detail: str) -> None:
    CampaignRecipient.objects.filter(pk=row.pk).update(
        status=status, detail=detail[:300], claim_token=''
    )


def _finish_if_done(campaign: Campaign, now: datetime, result: RunResult) -> None:
    open_rows = campaign.recipients.filter(
        status__in=[CampaignRecipient.PENDING, CampaignRecipient.SENDING]
    ).exists()
    if open_rows:
        return
    if Campaign.objects.filter(pk=campaign.pk, status=Campaign.SENDING).update(
        status=Campaign.COMPLETED, finished_at=now
    ):
        result.completed += 1
