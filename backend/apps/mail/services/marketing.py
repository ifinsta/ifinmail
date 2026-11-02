"""Marketing campaigns: one message to many people, one email each (Marketing plugin).

Transactional mail (a receipt, a password reset) goes to one person who just did something. A
campaign goes to a list, and the large providers judge the sender by how the list reacts. So a
campaign is not ``POST /messages`` in a loop:

* each recipient gets their own email, with a personal one-click unsubscribe link and the
  ``List-Unsubscribe`` headers (RFC 8058), and the sender's postal address in the footer;
* unsubscribing stops *marketing* mail only. ``MarketingOptOut`` is separate from the suppression
  list, which stops all API mail and would cost a newsletter reader their receipts;
* recipients on the suppression list (an address that does not exist, an unsubscribe through the
  Sender compliance plugin), on the opt-out list, or blocked by Outbound policy are skipped, and
  a person whose merge values are missing is skipped rather than greeted with "Hi ,";
* sending is paced by the runner (``campaign_runner``): a pace per minute and a daily ceiling that
  grows from a low start, instead of the per-key and per-mailbox counters of transactional mail.

This module creates campaigns and changes their state; the runner sends them. Failures carry a
status and a message that are safe to show.
"""

from __future__ import annotations

import html as html_lib
import logging
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from django.core import signing
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from backend.apps.accounts.services.tokens import sender_allowed
from backend.apps.core.plugins.services import InstallationService
from backend.apps.domains.models import Domain
from backend.apps.mail.models import (
    Audience,
    Campaign,
    CampaignRecipient,
    MarketingOptOut,
    Suppression,
)
from backend.apps.mail.services import containment
from backend.apps.mail.services.messages import (
    MAX_BODY_CHARS,
    SendRefused,
    address,
    blocked_destinations,
    internal_only_senders,
    is_blocked,
)

logger = logging.getLogger('backend')

CAPABILITY = 'marketing.campaigns'
MAX_MERGE_KEYS = 20
MAX_MERGE_VALUE = 200
_LOOKUP_CHUNK = 500  # addresses per database lookup

_OPTOUT_SALT = 'ifinmail.marketing.optout.v1'
_OPTOUT_MAX_AGE = 5 * 365 * 24 * 3600  # an old email's link keeps working for years

# {{first_name}} or {{first_name|there}}: a name, and an optional fallback for a missing value.
_TAG = re.compile(r'\{\{\s*([a-z][a-z0-9_]{0,39})\s*(?:\|\s*([^{}|\r\n]{0,60}?)\s*)?\}\}')
_NAME = re.compile(r'^[a-z][a-z0-9_]{0,39}$')
BUILTIN_TAGS = frozenset({'email', 'unsubscribe_url'})


# ------------------------------------------------------------------------------ settings


@dataclass(frozen=True)
class MarketingSettings:
    enabled: bool
    pace_per_minute: int
    daily_ceiling: int
    warmup: bool
    warmup_start: int
    max_recipients: int
    max_audience_size: int
    postal_address: str


def _number(value: str | None, default: int, low: int, high: int) -> int:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return number if low <= number <= high else default


def settings() -> MarketingSettings:
    values = InstallationService.capability_values(CAPABILITY)
    return MarketingSettings(
        enabled=values.get('enabled') == 'yes',
        pace_per_minute=_number(values.get('pace_per_minute'), 60, 1, 6000),
        daily_ceiling=_number(values.get('daily_ceiling'), 2000, 1, 1_000_000),
        warmup=values.get('warmup', 'yes') == 'yes',
        warmup_start=_number(values.get('warmup_start'), 200, 10, 100_000),
        max_recipients=_number(values.get('max_recipients'), 10_000, 1, 100_000),
        max_audience_size=_number(values.get('max_audience_size'), 100_000, 1, 1_000_000),
        postal_address=(values.get('postal_address') or '').strip(),
    )


# ------------------------------------------------------------------------------ merge tags


class MissingValue(Exception):  # noqa: N818
    """A merge tag with no value and no fallback."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


def tags_in(*texts: str) -> list[tuple[str, str | None]]:
    """``(name, fallback)`` for every merge tag in the texts, in order of appearance."""
    return [(m.group(1), m.group(2)) for text in texts for m in _TAG.finditer(text or '')]


def render(template: str, values: Mapping[str, str], *, escape: bool) -> str:
    """Fill the merge tags. ``escape`` for HTML: a value may hold ``<`` and must not become markup.

    A value that is missing or empty uses the tag's fallback; with none, ``MissingValue``.
    """

    def fill(match: re.Match[str]) -> str:
        name, fallback = match.group(1), match.group(2)
        value = values.get(name)
        if value is None or value == '':
            value = fallback
        if value is None:
            raise MissingValue(name)
        return html_lib.escape(value, quote=True) if escape else value

    return _TAG.sub(fill, template or '')


def clean_merge(raw: object) -> dict[str, str] | None:
    """One recipient's merge values, or ``None`` when they are not acceptable."""
    if raw is None:
        return {}
    if not isinstance(raw, Mapping) or len(raw) > MAX_MERGE_KEYS:
        return None
    clean: dict[str, str] = {}
    for key, value in raw.items():
        name = str(key).strip().lower()
        if not _NAME.match(name) or name in BUILTIN_TAGS:
            return None
        if value is None:
            continue
        if not isinstance(value, str | int | float) or isinstance(value, bool):
            return None
        text = str(value).strip()
        if len(text) > MAX_MERGE_VALUE:
            return None
        clean[name] = text
    return clean


_clean_merge = clean_merge  # the name the service and its tests used before it was public

# ------------------------------------------------------------------------------ opt-outs


def optout_token(domain: str, recipient: str) -> str:
    return signing.dumps(
        {'d': domain.lower(), 'r': recipient.lower()}, salt=_OPTOUT_SALT, compress=True
    )


def read_optout_token(token: str) -> tuple[str, str] | None:
    try:
        data = signing.loads(token, salt=_OPTOUT_SALT, max_age=_OPTOUT_MAX_AGE)
    except signing.BadSignature:
        return None
    return str(data.get('d', '')), str(data.get('r', ''))


def unsubscribe_url(domain: str, recipient: str) -> str:
    from backend.config import site_url

    return site_url.absolute_url(None, 'marketing_unsubscribe', optout_token(domain, recipient))


def opted_out(domain: str, addresses: Iterable[str]) -> set[str]:
    wanted = [a.lower() for a in addresses]
    found: set[str] = set()
    for start in range(0, len(wanted), _LOOKUP_CHUNK):
        found.update(
            MarketingOptOut.objects.filter(
                domain=domain.lower(), address__in=wanted[start : start + _LOOKUP_CHUNK]
            ).values_list('address', flat=True)
        )
    return found


def opt_out(domain: str, recipient: str, source: str = MarketingOptOut.ONE_CLICK) -> bool:
    """Record it; returns False when the address had already opted out."""
    _, created = MarketingOptOut.objects.get_or_create(
        domain=domain.lower(), address=recipient.strip().lower(), defaults={'source': source}
    )
    return created


def remove_opt_out(domain: str, recipient: str) -> int:
    deleted, _ = MarketingOptOut.objects.filter(
        domain=domain.lower(), address=recipient.strip().lower()
    ).delete()
    return deleted


def _suppressed(domain: str, addresses: list[str]) -> set[str]:
    """The suppression list applies to campaigns whether or not Sender compliance is installed:
    an address that bounced for good must not be mailed again by a list."""
    found: set[str] = set()
    for start in range(0, len(addresses), _LOOKUP_CHUNK):
        found.update(
            Suppression.objects.filter(
                domain=domain, address__in=addresses[start : start + _LOOKUP_CHUNK]
            ).values_list('address', flat=True)
        )
    return found


def skip_reasons(domain: str, addresses: list[str]) -> dict[str, str]:
    """``{address: reason}`` for the addresses a campaign from ``domain`` must not mail.

    The same rules at creation and again when an email is about to go out: a person can
    unsubscribe, or an address can bounce, in between.
    """
    gone = _suppressed(domain, addresses)
    declined = opted_out(domain, addresses)
    patterns = blocked_destinations()
    reasons: dict[str, str] = {}
    for who in addresses:
        if who in gone:
            reasons[who] = 'suppressed: on the suppression list'
        elif who in declined:
            reasons[who] = 'opted_out: unsubscribed from marketing mail'
        elif is_blocked(who, patterns):
            reasons[who] = 'blocked: Outbound policy forbids this destination'
    return reasons


# ------------------------------------------------------------------------------ composing


@dataclass(frozen=True)
class Composed:
    subject: str
    text: str
    html: str
    unsubscribe_url: str


def _footer_html(postal: str, url: str) -> str:
    return (
        '<p style="margin:24px 0 0;font-size:12px;color:#6b7280">'
        f'{html_lib.escape(postal)}<br>'
        f'<a href="{html_lib.escape(url, quote=True)}">Unsubscribe</a></p>'
    )


def compose(
    campaign: Campaign, recipient: str, merge: Mapping[str, str], postal_address: str
) -> Composed:
    """The email one person gets: merge tags filled in, then the footer with the unsubscribe link.

    The footer is always added (it is the law, not a style): a campaign cannot leave it out.
    """
    domain = campaign.sender.rpartition('@')[2]
    url = unsubscribe_url(domain, recipient)
    values = {**merge, 'email': recipient, 'unsubscribe_url': url}
    subject = render(campaign.subject, {k: _one_line(v) for k, v in values.items()}, escape=False)
    text = html = ''
    if campaign.text.strip():
        text = render(campaign.text, values, escape=False)
        text = f'{text.rstrip()}\n\n-- \n{postal_address}\nUnsubscribe: {url}\n'
    if campaign.html.strip():
        html = render(campaign.html, values, escape=True)
        footer = _footer_html(postal_address, url)
        end = html.lower().rfind('</body>')
        html = f'{html[:end]}{footer}{html[end:]}' if end != -1 else f'{html}{footer}'
    return Composed(subject=_one_line(subject), text=text, html=html, unsubscribe_url=url)


def _one_line(value: str) -> str:
    return ' '.join(value.split())


# ------------------------------------------------------------------------------ creating


@dataclass(frozen=True)
class RecipientIn:
    address: str
    merge: Mapping[str, object] | None = None


@dataclass(frozen=True)
class CampaignRequest:
    sender: str
    subject: str
    text: str | None
    html: str | None
    recipients: tuple[RecipientIn, ...] = ()
    reply_to: str | None = None
    name: str = ''
    audience: Audience | None = None  # instead of ``recipients``: everyone on the list, as now


@dataclass(frozen=True)
class CampaignKey:
    """What the campaign needs to know about the key making the call."""

    prefix: str
    name: str
    allowed_senders: tuple[str, ...]
    sandbox: bool = False


@dataclass(frozen=True)
class Created:
    campaign: Campaign
    queued: int
    skipped: dict[str, int] = field(default_factory=dict)  # reason -> how many


def _skip_reason_key(detail: str) -> str:
    return detail.split(':', 1)[0]


def create(request: CampaignRequest, key: CampaignKey) -> Created:
    cfg = settings()
    if not cfg.enabled:
        raise SendRefused(
            403, 'Marketing is switched off. Install or enable the Marketing plugin to use it.'
        )
    if not cfg.postal_address:
        raise SendRefused(
            409,
            'Campaigns need your postal address in the footer. An administrator sets it under '
            'Marketplace, Marketing, "Postal address for the footer".',
        )
    if key.sandbox:
        raise SendRefused(403, 'A sandbox key cannot run campaigns; use a normal key.')

    sender = address(request.sender)
    domain = sender.rpartition('@')[2]
    reply_to = address(request.reply_to) if request.reply_to else ''
    subject = (request.subject or '').strip()
    if not subject or '\n' in subject or '\r' in subject:
        raise SendRefused(422, 'The subject is required and must be a single line.')
    text, html = request.text or '', request.html or ''
    if not text.strip() and not html.strip():
        raise SendRefused(422, 'Send a text body, an html body, or both.')
    if len(text) + len(html) > MAX_BODY_CHARS:
        raise SendRefused(413, f'The message body is limited to {MAX_BODY_CHARS} characters.')
    if request.audience is not None and request.recipients:
        raise SendRefused(422, 'Name an audience or list recipients, not both.')
    recipients: Sequence[RecipientIn] = request.recipients
    if request.audience is None:
        if not recipients:
            raise SendRefused(422, 'Name at least one recipient, or an audience to send to.')
        if len(recipients) > cfg.max_recipients:
            raise SendRefused(
                422, f'A campaign may have at most {cfg.max_recipients} recipients on this server.'
            )

    if not sender_allowed(list(key.allowed_senders), sender):
        raise SendRefused(403, f'This key may not send as {sender}.')
    if not Domain.objects.filter(name=domain).exists():
        raise SendRefused(403, f'{domain} is not a domain on this server.')
    if sender in containment.paused():
        raise SendRefused(
            403, f'Sending is paused for {sender}. An administrator must resume it first.'
        )
    if sender in internal_only_senders():
        raise SendRefused(403, f'{sender} may only send to domains hosted here, not run campaigns.')
    from backend.apps.mail.services import compliance

    if compliance.settings().enabled and key.prefix:
        stopped = compliance.paused(key.prefix)
        if stopped:
            raise SendRefused(
                403,
                f'This key is paused: {stopped["rate"]}% of its {stopped["total"]} messages '
                'today bounced. Clean the list, then ask an administrator to resume it.',
            )

    if request.audience is not None:
        if request.audience.domain != domain:
            raise SendRefused(
                422,
                f'The audience belongs to {request.audience.domain}; a campaign to it must be '
                f'sent from an address at that domain, not {domain}.',
            )
        recipients = [
            RecipientIn(address=who, merge=merge)
            for who, merge in request.audience.contacts.order_by('pk').values_list(
                'address', 'merge'
            )
        ]
        if not recipients:
            raise SendRefused(422, 'The audience has no contacts yet.')

    # Merge tags: a tag nobody can fill is a typo; a person missing a value is skipped.
    without_fallback = {name for name, fallback in tags_in(subject, text, html) if fallback is None}
    required = sorted(without_fallback - BUILTIN_TAGS)
    provided: set[str] = set()
    for item in recipients:
        clean = clean_merge(item.merge)
        if clean:
            provided.update(clean)
    typos = [name for name in required if name not in provided]
    if typos:
        raise SendRefused(
            422,
            'The message uses merge tags no recipient has a value for: '
            + ', '.join('{{' + name + '}}' for name in typos)
            + '. Add the values, or write a fallback such as {{first_name|there}}.',
        )

    rows: dict[str, tuple[dict[str, str], str]] = {}  # address -> (merge, skip detail)
    skipped: Counter[str] = Counter()
    for item in recipients:
        try:
            who = address(item.address)
        except SendRefused:
            skipped['invalid'] += 1
            continue
        if who in rows:
            skipped['duplicate'] += 1
            continue
        clean = clean_merge(item.merge)
        if clean is None:
            skipped['invalid'] += 1
            continue
        missing = [name for name in required if not clean.get(name)]
        rows[who] = (clean, f'missing: {", ".join(missing)}' if missing else '')

    refused = skip_reasons(domain, list(rows))
    for who, (merge, detail) in list(rows.items()):
        detail = refused.get(who, detail)
        rows[who] = (merge, detail)
        if detail:
            skipped[_skip_reason_key(detail)] += 1

    queued = sum(1 for _, detail in rows.values() if not detail)
    if not queued:
        summary = ', '.join(f'{count} {reason}' for reason, count in skipped.items()) or 'none'
        raise SendRefused(422, f'Nobody is left to send to ({summary}); nothing was created.')

    with transaction.atomic():
        campaign = Campaign.objects.create(
            name=(request.name or '').strip()[:120],
            key_prefix=key.prefix,
            key_name=key.name[:64],
            sender=sender,
            reply_to=reply_to,
            subject=subject,
            text=text,
            html=html,
            audience=request.audience,
        )
        CampaignRecipient.objects.bulk_create(
            [
                CampaignRecipient(
                    campaign=campaign,
                    address=who,
                    merge=merge,
                    status=CampaignRecipient.SKIPPED if detail else CampaignRecipient.PENDING,
                    detail=detail,
                )
                for who, (merge, detail) in rows.items()
            ],
            batch_size=1000,
        )
    return Created(campaign=campaign, queued=queued, skipped=dict(skipped))


# ------------------------------------------------------------------------------ bounces

BOUNCE_COUNT_SECONDS = 30 * 24 * 3600
GUARD_MIN_SENT = 100  # a bounce rate over fewer emails than this is noise
GUARD_MAX_BOUNCE_PERCENT = 5.0  # the level at which the large providers start to refuse


def _bounce_key(campaign_id: str) -> str:
    return f'marketing:bounced:{campaign_id}'


def note_bounce(
    campaign_id: str, sender: str, recipient: str, category: str, dsn: str, reason: str
) -> None:
    """From the delivery log: an email of a campaign bounced.

    A permanent failure for a reason that will not change (the address does not exist) adds the
    address to the suppression list, whether or not Sender compliance is installed: a list must
    not keep mailing an address that bounced. Every bounce counts towards the campaign's guard.
    """
    from backend.apps.mail.services import compliance

    if compliance.is_hard_bounce(category, dsn):
        domain = sender.rpartition('@')[2].lower()
        compliance.suppress(domain, recipient, Suppression.BOUNCED, detail=f'{dsn} {reason}'[:300])
    try:
        cache.add(_bounce_key(campaign_id), 0, BOUNCE_COUNT_SECONDS)
        cache.incr(_bounce_key(campaign_id))
    except Exception:
        logger.warning('Marketing bounce counters unavailable')


def bounce_rate(campaign: Campaign, sent: int | None = None) -> tuple[float | None, int]:
    """``(percent, sent)``: how much of what the campaign has sent has bounced so far.

    ``sent`` saves the count when the caller already has it."""
    if sent is None:
        sent = campaign.recipients.filter(status=CampaignRecipient.SENT).count()
    try:
        bounced = int(cache.get(_bounce_key(str(campaign.pk))) or 0)
    except Exception:
        return None, sent
    return (round(100 * bounced / sent, 1) if sent else None), sent


def over_bounce_limit(campaign: Campaign) -> str:
    """A reason to stop the campaign, or ``''``."""
    rate, sent = bounce_rate(campaign)
    if rate is not None and sent >= GUARD_MIN_SENT and rate > GUARD_MAX_BOUNCE_PERCENT:
        return (
            f'{rate}% of the {sent} emails sent so far bounced. Clean the list, then resume '
            'the campaign or cancel it.'
        )
    return ''


# ------------------------------------------------------------------------------ state


_STATUSES = (
    CampaignRecipient.PENDING,
    CampaignRecipient.SENDING,
    CampaignRecipient.SENT,
    CampaignRecipient.FAILED,
    CampaignRecipient.SKIPPED,
)


def counts_for(campaigns: Iterable[Campaign]) -> dict[object, dict[str, int]]:
    """Recipients by status for many campaigns in one query: ``{campaign pk: {status: n}}``."""
    found = {campaign.pk: dict.fromkeys(_STATUSES, 0) for campaign in campaigns}
    rows = (
        CampaignRecipient.objects.filter(campaign_id__in=list(found))
        .values('campaign_id', 'status')
        .order_by()
        .annotate(n=Count('pk'))
    )
    for row in rows:
        found[row['campaign_id']][row['status']] = row['n']
    return found


def counts(campaign: Campaign) -> dict[str, int]:
    """Recipients by status, with every status present."""
    return counts_for([campaign])[campaign.pk]


def pause(campaign: Campaign, reason: str = 'Paused by a person.') -> bool:
    """Stop sending until resumed. Returns False when it is not being sent."""
    return bool(
        Campaign.objects.filter(pk=campaign.pk, status=Campaign.SENDING).update(
            status=Campaign.PAUSED, status_detail=reason[:300]
        )
    )


def resume(campaign: Campaign) -> bool:
    return bool(
        Campaign.objects.filter(pk=campaign.pk, status=Campaign.PAUSED).update(
            status=Campaign.SENDING, status_detail=''
        )
    )


def cancel(campaign: Campaign) -> bool:
    """End it for good: what has not been sent will not be. Returns False when already over."""
    now: datetime = timezone.now()
    done = Campaign.objects.filter(
        pk=campaign.pk, status__in=[Campaign.SENDING, Campaign.PAUSED]
    ).update(status=Campaign.CANCELLED, status_detail='', finished_at=now)
    return bool(done)


__all__ = [
    'BUILTIN_TAGS',
    'CampaignKey',
    'CampaignRequest',
    'Composed',
    'Created',
    'MarketingSettings',
    'MissingValue',
    'RecipientIn',
    'cancel',
    'clean_merge',
    'compose',
    'bounce_rate',
    'note_bounce',
    'over_bounce_limit',
    'counts',
    'counts_for',
    'create',
    'opt_out',
    'opted_out',
    'pause',
    'read_optout_token',
    'remove_opt_out',
    'render',
    'resume',
    'skip_reasons',
    'settings',
    'tags_in',
    'unsubscribe_url',
]
