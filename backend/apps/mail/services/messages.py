"""Sending one message on behalf of an API key (``POST /api/v1/messages``).

The message goes to the internal relay (port 10025), which signs it with DKIM and delivers it.
That relay trusts the Docker network and checks nothing about who the sender is, so every
guard that submission on 587/465 gets from Postfix is applied here instead, before the relay:

* the From address must be one the key names (or on a ``*@domain`` it names), on a hosted domain;
* a mailbox that containment paused cannot send;
* the Outbound policy plugin's limits apply: recipients per message, blocked destinations,
  internal-only mailboxes, and messages per minute and per day for the From address;
* the key has its own daily cap on recipients;
* what was sent feeds the same counters containment reads, so a flood through a key is noticed
  like a flood through a password.

Nothing here stores the message. Failures carry a status and a message that is safe to show.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import logging
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import make_msgid
from smtplib import SMTPException

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives, get_connection
from django.core.validators import validate_email
from django.utils.html import strip_tags

from backend.apps.accounts.services.tokens import sender_allowed
from backend.apps.core.plugins.services import InstallationService
from backend.apps.domains.models import Domain
from backend.apps.mail.services import containment

logger = logging.getLogger('backend')

DEFAULT_PER_DAY = 500  # recipients one key may write to per day (API_SEND_LIMIT_PER_DAY)
MAX_RECIPIENTS = 100  # the ceiling for one message; the plugin may set it lower
MAX_BODY_CHARS = 1_000_000
SMTP_TIMEOUT_SECONDS = 10
_ADDRESS_ILLEGAL = re.compile(r'[\s<>,;"\\\x00-\x1f]')


class SendRefused(Exception):  # noqa: N818  (reads better as a verdict than as an error type)
    """A send that cannot go ahead. ``status`` is the HTTP status; ``message`` is safe to show."""

    def __init__(self, status: int, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.retry_after = retry_after


@dataclass(frozen=True)
class SendRequest:
    sender: str
    to: tuple[str, ...]
    cc: tuple[str, ...]
    bcc: tuple[str, ...]
    reply_to: str | None
    subject: str
    text: str | None
    html: str | None


@dataclass(frozen=True)
class SendingKey:
    """What the sender needs to know about the key making the call."""

    key_id: str  # "ifm_<prefix>", for counters and the audit trail
    allowed_senders: tuple[str, ...]
    daily_recipients: int | None  # None: the server default
    sandbox: bool = False  # capture instead of delivering (Developer sandbox)
    prefix: str = ''
    name: str = ''
    agent: bool = False  # the key manages agent inboxes (Human approval may apply)
    approved: bool = False  # a person approved this message (Human approval): send it now


@dataclass(frozen=True)
class Receipt:
    message_id: str
    recipients: int
    captured: bool = False  # a sandbox key's message, kept and not delivered
    pending_id: str = ''  # held for a person's approval (Human approval plugin)


def address(raw: str) -> str:
    """One bare address, lower-cased; ``SendRefused(422)`` for anything else."""
    text = (raw or '').strip().lower()
    if not text or len(text) > 254 or _ADDRESS_ILLEGAL.search(text):
        raise SendRefused(422, f'"{raw[:80]}" is not a plain email address.')
    try:
        validate_email(text)
    except ValidationError as exc:
        raise SendRefused(422, f'"{raw[:80]}" is not a valid email address.') from exc
    return text


def _unique(addresses: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for item in addresses:
        seen.setdefault(item, None)
    return list(seen)


def _words(value: str) -> list[str]:
    return [w for w in re.split(r'[\s,;]+', (value or '').lower()) if w]


def _blocked(recipient: str, patterns: list[str]) -> bool:
    """An address or a domain (subdomains included), as the Outbound policy plugin writes them."""
    domain = recipient.rpartition('@')[2]
    for pattern in patterns:
        if '@' in pattern:
            if recipient == pattern:
                return True
        elif domain == pattern or domain.endswith(f'.{pattern}'):
            return True
    return False


def _seconds_to_midnight(now: datetime) -> int:
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(int((tomorrow - now).total_seconds()), 1)


def _take(key: str, amount: int, limit: int, ttl: int, retry_after: int, what: str) -> None:
    """Add ``amount`` to a counter, or refuse (and leave it unchanged) when that passes ``limit``.

    The cache is the only record; if it is down the send is refused, because an unlimited
    sender is worse than an unavailable one.
    """
    try:
        cache.add(key, 0, timeout=ttl)
        used = int(cache.incr(key, amount))
    except Exception as exc:
        logger.warning('Send quota store unavailable: %s', exc)
        raise SendRefused(503, 'Sending is temporarily unavailable. Try again shortly.') from exc
    if used > limit:
        try:
            cache.decr(key, amount)
        except Exception:  # the window expires on its own
            logger.warning('Could not return %s to %s', amount, key)
        raise SendRefused(429, f'The {what} of {limit} is used up.', retry_after=retry_after)


def _refund(key: str, amount: int) -> None:
    try:
        cache.decr(key, amount)
    except Exception:
        logger.warning('Could not return %s to %s', amount, key)


def _cap_per_day(key: SendingKey) -> int:
    if key.daily_recipients:
        return key.daily_recipients
    try:
        value = int(os.environ.get('API_SEND_LIMIT_PER_DAY', DEFAULT_PER_DAY))
    except ValueError:
        return DEFAULT_PER_DAY
    return value if value > 0 else DEFAULT_PER_DAY


def _number(value: str | None) -> int | None:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _own_inbox(key: SendingKey, sender: str) -> bool:
    """A key may send as the agent inboxes it created (Agent inboxes plugin)."""
    if not key.prefix:
        return False
    from backend.apps.mail.services import agent_inboxes

    return agent_inboxes.settings().enabled and agent_inboxes.owns(key.prefix, sender)


class MessageService:
    @staticmethod
    def send(request: SendRequest, key: SendingKey, *, now: datetime | None = None) -> Receipt:
        now = now or datetime.now(UTC)
        sender = address(request.sender)
        domain = sender.rpartition('@')[2]
        recipients = _unique(
            [address(a) for a in (*request.to, *request.cc, *request.bcc)],
        )
        reply_to = address(request.reply_to) if request.reply_to else None
        subject = (request.subject or '').strip()
        if not subject or '\n' in subject or '\r' in subject:
            raise SendRefused(422, 'The subject is required and must be a single line.')
        text, html = request.text or '', request.html or ''
        if not text.strip() and not html.strip():
            raise SendRefused(422, 'Send a text body, an html body, or both.')
        if len(text) + len(html) > MAX_BODY_CHARS:
            raise SendRefused(413, f'The message body is limited to {MAX_BODY_CHARS} characters.')
        if not recipients:
            raise SendRefused(422, 'Name at least one recipient.')

        # Who may send as this address.
        if not sender_allowed(list(key.allowed_senders), sender) and not _own_inbox(key, sender):
            raise SendRefused(403, f'This key may not send as {sender}.')
        if not Domain.objects.filter(name=domain).exists():
            raise SendRefused(403, f'{domain} is not a domain on this server.')
        if sender in containment.paused():
            raise SendRefused(
                403, f'Sending is paused for {sender}. An administrator must resume it first.'
            )

        # Outbound policy (the plugin's settings), applied as submission would apply them.
        limits = InstallationService.capability_values('sending.recipient_limits')
        most = min(MAX_RECIPIENTS, _number(limits.get('per_message')) or MAX_RECIPIENTS)
        if len(recipients) > most:
            raise SendRefused(422, f'A message may have at most {most} recipients.')
        blocked = _words(
            InstallationService.capability_values('sending.blocked_destinations').get('domains', '')
        )
        for recipient in recipients:
            if _blocked(recipient, blocked):
                raise SendRefused(403, f'Sending to {recipient} is not allowed on this server.')
        internal = _words(
            InstallationService.capability_values('sending.internal_only').get('mailboxes', '')
        )
        if sender in internal:
            hosted = set(
                Domain.objects.filter(
                    name__in={r.rpartition('@')[2] for r in recipients}
                ).values_list('name', flat=True)
            )
            outside = [r for r in recipients if r.rpartition('@')[2] not in hosted]
            if outside:
                raise SendRefused(403, f'{sender} may only send to domains hosted here.')

        # A sandbox key stops here: everything above was checked like a real send, and the
        # message is kept for inspection. It never reaches the relay, the quotas or containment.
        if key.sandbox:
            from backend.apps.mail.services import sandbox

            box = sandbox.settings()
            if not box.enabled:
                raise SendRefused(
                    403,
                    'This is a sandbox key and the Developer sandbox plugin is off, so nothing '
                    'was sent. Install or enable it to capture test mail.',
                )
            message_id = make_msgid(domain=domain).strip('<>')
            sandbox.capture(
                key_prefix=key.prefix,
                key_name=key.name,
                message_id=message_id,
                sender=sender,
                to=[address(a) for a in request.to],
                cc=[address(a) for a in request.cc],
                bcc=[address(a) for a in request.bcc],
                reply_to=reply_to or '',
                subject=subject,
                text=text,
                html=html,
                keep=box.max_messages,
            )
            return Receipt(message_id=message_id, recipients=len(recipients), captured=True)

        # Human approval: a message the plugin's rule holds waits for a person.
        if not key.approved:
            from backend.apps.mail.services import approvals

            reason = approvals.reason_to_hold(
                agent_key=key.agent, sender=sender, recipients=recipients
            )
            if reason:
                held = approvals.hold(
                    key_prefix=key.prefix, key_name=key.name, request=request, reason=reason
                )
                return Receipt(
                    message_id='', recipients=len(recipients), pending_id=str(held.pk)
                )

        # Quotas: the key's recipients per day, then the From address's messages per minute/day.
        until_midnight = _seconds_to_midnight(now)
        stamp = now.strftime('%Y%m%d')
        taken: list[tuple[str, int]] = []
        try:
            day_key = f'apisend:key:{key.key_id}:{stamp}'
            _take(
                day_key,
                len(recipients),
                _cap_per_day(key),
                until_midnight + 3600,
                until_midnight,
                'daily recipient limit',
            )
            taken.append((day_key, len(recipients)))
            rate = InstallationService.capability_values('sending.rate_limit')
            per_minute = _number(rate.get('per_minute'))
            per_day = _number(rate.get('per_day'))
            if per_minute:
                minute_key = f'apisend:from:{sender}:{now.strftime("%Y%m%d%H%M")}'
                _take(minute_key, 1, per_minute, 120, 60 - now.second, 'per-minute message limit')
                taken.append((minute_key, 1))
            if per_day:
                from_day = f'apisend:from:{sender}:{stamp}'
                _take(
                    from_day,
                    1,
                    per_day,
                    until_midnight + 3600,
                    until_midnight,
                    'daily message limit',
                )
                taken.append((from_day, 1))
        except SendRefused:
            for counter, amount in taken:
                _refund(counter, amount)
            raise

        message_id = make_msgid(domain=domain)
        body = text if text.strip() else html_lib.unescape(strip_tags(html))
        mail = EmailMultiAlternatives(
            subject=subject,
            body=body,
            from_email=sender,
            to=[address(a) for a in request.to],
            cc=[address(a) for a in request.cc] or None,
            bcc=[address(a) for a in request.bcc] or None,
            reply_to=[reply_to] if reply_to else None,
            headers={'Message-ID': message_id, 'X-Mailer': 'ifinmail-api'},
            connection=get_connection(fail_silently=False, timeout=SMTP_TIMEOUT_SECONDS),
        )
        if html.strip():
            mail.attach_alternative(html, 'text/html')
        try:
            mail.send()
        except (SMTPException, OSError) as exc:
            for counter, amount in taken:
                _refund(counter, amount)
            logger.warning('API send was not accepted by the relay: %s', exc)
            raise SendRefused(
                502, 'The mail server did not accept the message. Try again shortly.'
            ) from exc

        containment.record_send(sender, recipients)
        from backend.apps.mail.services import approvals

        if approvals.settings().enabled:
            approvals.remember_contacts(sender, recipients)
        return Receipt(message_id=message_id.strip('<>'), recipients=len(recipients))


def digest(value: str) -> str:
    """A short stable hash of the request, for idempotency comparisons."""
    return hashlib.sha256(value.encode()).hexdigest()


__all__ = ['MessageService', 'Receipt', 'SendRefused', 'SendRequest', 'SendingKey', 'address']
