"""Webhooks: the server POSTs signed JSON events to URLs its users choose.

Used by the Delivery Events plugin (what became of mail sent through the API) and the Inbox
Webhooks plugin (mail a mailbox received). Each event is stored once per endpoint and delivered
by the worker with retries, so a slow or failing receiver never slows mail down.

What a receiver gets::

    POST <url>
    Content-Type: application/json
    X-Ifinmail-Event: message.bounced
    X-Ifinmail-Event-Id: evt_5f0c...        (the same on every retry: deduplicate on it)
    X-Ifinmail-Signature: t=1760000000,v1=<hex HMAC-SHA256 of "<t>.<body>" with the secret>

    {"id": "evt_5f0c...", "type": "message.bounced", "created": "2026-10-15T09:12:03Z",
     "data": {...}}

Safety: the URL must be https (http only when the plugin allows it), it may not resolve to the
server itself, a link-local or metadata address, or (unless allowed) a private network; it is
checked again at every attempt, redirects are not followed, and an answer is read only up to
a few kilobytes. A ``410 Gone`` switches the endpoint off.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import secrets as pysecrets
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlsplit

from django.db import IntegrityError, transaction
from django.utils import timezone

from backend.apps.core.plugins.services import InstallationService
from backend.apps.core.plugins.services import secrets as plugin_secrets
from backend.apps.mail.models import WebhookDelivery, WebhookEndpoint
from backend.apps.mail.types.events import SUBSCRIBABLE, EventType

logger = logging.getLogger('backend')

TIMEOUT_SECONDS = 10
MAX_ENDPOINTS_PER_OWNER = 10
MAX_RESPONSE_BYTES = 4096
# Wait before attempt n+1 (seconds): 1 min, 5 min, 30 min, 2 h, 6 h, 12 h, 24 h.
BACKOFF = (60, 300, 1800, 7200, 21600, 43200, 86400)
KEEP_DAYS = 14  # delivered and failed attempts kept for this long

_ALWAYS_BLOCKED = (
    ipaddress.ip_network('127.0.0.0/8'),
    ipaddress.ip_network('::1/128'),
    ipaddress.ip_network('0.0.0.0/8'),
    ipaddress.ip_network('169.254.0.0/16'),  # link-local, cloud metadata 169.254.169.254
    ipaddress.ip_network('fe80::/10'),
    ipaddress.ip_network('fd00:ec2::/32'),
    ipaddress.ip_network('224.0.0.0/4'),
    ipaddress.ip_network('ff00::/8'),
)
_PRIVATE = (
    ipaddress.ip_network('10.0.0.0/8'),
    ipaddress.ip_network('172.16.0.0/12'),  # includes Docker's networks
    ipaddress.ip_network('192.168.0.0/16'),
    ipaddress.ip_network('100.64.0.0/10'),
    ipaddress.ip_network('fc00::/7'),
)
_BLOCKED_HOSTS = {'localhost', 'metadata.google.internal', 'metadata'}


class WebhookError(ValueError):
    """Something the person can fix; the message is safe to show."""


@dataclass(frozen=True)
class Policy:
    """What the Delivery Events / Inbox Webhooks plugins allow."""

    delivery_events: bool
    inbox_events: bool
    allow_http: bool
    allow_private: bool
    max_attempts: int


def policy() -> Policy:
    events = InstallationService.capability_values('developer.events')
    inbox = InstallationService.capability_values('developer.inbox_webhooks')

    def flag(values: dict[str, str], name: str) -> bool:
        return values.get(name) == 'yes'

    try:
        attempts = int(events.get('max_attempts') or len(BACKOFF) + 1)
    except ValueError:
        attempts = len(BACKOFF) + 1
    return Policy(
        delivery_events=flag(events, 'enabled'),
        inbox_events=flag(inbox, 'enabled'),
        allow_http=flag(events, 'allow_http') or flag(inbox, 'allow_http'),
        allow_private=flag(events, 'allow_private') or flag(inbox, 'allow_private'),
        max_attempts=max(1, min(attempts, len(BACKOFF) + 1)),
    )


# ------------------------------------------------------------------------------ the address


def check_url(url: str, current: Policy | None = None, *, resolve: bool = True) -> str:
    """Refuse a URL that could reach this server or its private network. Returns it cleaned."""
    current = current or policy()
    url = (url or '').strip()
    parts = urlsplit(url)
    if parts.scheme not in ('https', 'http') or not parts.hostname or len(url) > 500:
        raise WebhookError('Use a full https:// address.')
    if parts.scheme == 'http' and not current.allow_http:
        raise WebhookError('Use https:// (plain http is off in the plugin settings).')
    if parts.username or parts.password:
        raise WebhookError('Do not put credentials in the address; verify the signature instead.')
    host = parts.hostname.lower().rstrip('.')
    if host in _BLOCKED_HOSTS or host.endswith('.localhost') or '.' not in host and not _is_ip(host):
        # A bare name ("redis", "api") is a service on this server's own network.
        raise WebhookError(f'{host} is not a public address.')
    if not resolve:
        return url
    try:
        infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == 'https' else 80))
    except OSError:
        raise WebhookError(f'{host} could not be resolved.') from None
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if any(address in net for net in _ALWAYS_BLOCKED):
            raise WebhookError(f'{host} resolves to {address}, which is not allowed.')
        if not current.allow_private and any(address in net for net in _PRIVATE):
            raise WebhookError(
                f'{host} resolves to a private address ({address}). Allow private networks in '
                'the plugin settings to use an endpoint on your own network.'
            )
    return url


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip('[]'))
    except ValueError:
        return False
    return True


# ------------------------------------------------------------------------------ endpoints


def create_endpoint(
    *,
    name: str,
    url: str,
    events: Iterable[str],
    owner_prefix: str = '',
    mailboxes: Iterable[str] = (),
    created_by: str = '',
) -> tuple[WebhookEndpoint, str]:
    """Create an endpoint; returns ``(row, secret)``. The secret is shown once."""
    current = policy()
    if not (current.delivery_events or current.inbox_events):
        raise WebhookError(
            'Install the Delivery Events or Inbox Webhooks plugin to send events to webhooks.'
        )
    clean_name = (name or '').strip()[:64]
    if not clean_name:
        raise WebhookError('Give the webhook a name.')
    wanted = sorted({str(e) for e in events})
    unknown = [e for e in wanted if e not in SUBSCRIBABLE]
    if unknown or not wanted:
        raise WebhookError(
            'Choose events from: ' + ', '.join(str(e) for e in SUBSCRIBABLE) + '.'
        )
    if EventType.RECEIVED in wanted and not current.inbox_events:
        raise WebhookError('message.received needs the Inbox Webhooks plugin.')
    if set(wanted) - {EventType.RECEIVED} and not current.delivery_events:
        raise WebhookError('Delivery events need the Delivery Events plugin.')
    boxes = sorted({m.strip().lower() for m in mailboxes if m.strip()})
    if EventType.RECEIVED in wanted and not boxes:
        raise WebhookError('Name the mailboxes whose received mail this webhook gets.')
    if EventType.RECEIVED in wanted:
        from backend.apps.mail.models import Mailbox

        for box in boxes:
            local, _, domain = box.partition('@')
            if not Mailbox.objects.filter(local_part=local, domain__name=domain).exists():
                raise WebhookError(f'{box} is not a mailbox on this server.')
    if WebhookEndpoint.objects.filter(owner_prefix=owner_prefix).count() >= MAX_ENDPOINTS_PER_OWNER:
        raise WebhookError(f'At most {MAX_ENDPOINTS_PER_OWNER} webhooks; remove one first.')
    clean_url = check_url(url, current)
    secret = 'whsec_' + pysecrets.token_urlsafe(32)
    row = WebhookEndpoint.objects.create(
        name=clean_name,
        url=clean_url,
        secret=plugin_secrets.encrypt(secret),
        events=wanted,
        owner_prefix=owner_prefix,
        mailboxes=boxes,
        created_by=created_by[:255],
    )
    return row, secret


def endpoints_for(owner_prefix: str | None) -> list[WebhookEndpoint]:
    """``None``: every endpoint (the console); a prefix: one key's own."""
    rows = WebhookEndpoint.objects.all()
    if owner_prefix is not None:
        rows = rows.filter(owner_prefix=owner_prefix)
    return list(rows)


def get_endpoint(endpoint_id: str, owner_prefix: str | None) -> WebhookEndpoint | None:
    try:
        row = WebhookEndpoint.objects.filter(pk=endpoint_id).first()
    except (ValueError, TypeError):
        return None
    if row is None or (owner_prefix is not None and row.owner_prefix != owner_prefix):
        return None
    return row


def set_active(row: WebhookEndpoint, active: bool) -> None:
    row.active = active
    if active:
        row.failing_since = None
        row.last_error = ''
    row.save(update_fields=['active', 'failing_since', 'last_error'])


# ------------------------------------------------------------------------------ events


def new_event_id() -> str:
    return 'evt_' + pysecrets.token_hex(12)


def emit(
    event_type: str,
    data: dict,
    *,
    key_prefix: str = '',
    mailbox: str = '',
    event_id: str | None = None,
) -> int:
    """Queue one event for every endpoint that wants it. Returns how many deliveries were made.

    Delivery events reach console endpoints and the sending key's own; received-mail events reach
    endpoints that list that mailbox.
    """
    current = policy()
    if event_type == EventType.RECEIVED:
        if not current.inbox_events:
            return 0
    elif not current.delivery_events:
        return 0
    event_id = event_id or new_event_id()
    payload = {
        'id': event_id,
        'type': str(event_type),
        'created': timezone.now().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'data': data,
    }
    made = []
    for row in WebhookEndpoint.objects.filter(active=True):
        if str(event_type) not in row.events:
            continue
        if event_type == EventType.RECEIVED:
            if mailbox.lower() not in row.mailboxes:
                continue
        elif row.owner_prefix and row.owner_prefix != key_prefix:
            continue
        try:
            with transaction.atomic():
                made.append(
                    WebhookDelivery.objects.create(
                        endpoint=row,
                        event_id=event_id,
                        event_type=str(event_type),
                        payload=payload,
                        next_attempt_at=timezone.now(),
                    )
                )
        except IntegrityError:  # this event was already queued for this endpoint
            continue
    for delivery in made:
        _schedule(str(delivery.pk))
    return len(made)


def ping(row: WebhookEndpoint) -> WebhookDelivery:
    """A test event for one endpoint, delivered now (for the Test button and the API)."""
    event_id = new_event_id()
    delivery = WebhookDelivery.objects.create(
        endpoint=row,
        event_id=event_id,
        event_type=EventType.PING,
        payload={
            'id': event_id,
            'type': str(EventType.PING),
            'created': timezone.now().strftime('%Y-%m-%dT%H:%M:%SZ'),
            'data': {'webhook': str(row.pk), 'name': row.name},
        },
        next_attempt_at=timezone.now(),
    )
    attempt(delivery)
    delivery.refresh_from_db()
    return delivery


def _schedule(delivery_id: str) -> None:
    from backend.apps.mail.tasks import deliver_webhook

    def queue() -> None:
        try:
            deliver_webhook.delay(delivery_id)
        except Exception:  # the broker is down: the sweep (every minute) picks it up
            logger.warning('Could not queue webhook delivery %s', delivery_id, exc_info=True)

    transaction.on_commit(queue)


# ------------------------------------------------------------------------------ delivery


def sign(secret: str, body: bytes, timestamp: int) -> str:
    mac = hmac.new(secret.encode(), f'{timestamp}.'.encode() + body, hashlib.sha256).hexdigest()
    return f't={timestamp},v1={mac}'


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        return None


_OPENER = urllib.request.build_opener(_NoRedirect())


def _post(url: str, body: bytes, headers: dict[str, str]) -> int:
    request = urllib.request.Request(url, data=body, headers=headers, method='POST')
    try:
        with _OPENER.open(request, timeout=TIMEOUT_SECONDS) as response:
            response.read(MAX_RESPONSE_BYTES)
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def attempt(delivery: WebhookDelivery) -> bool:
    """Try one delivery now. Returns True when the receiver answered 2xx."""
    row = delivery.endpoint
    current = policy()
    now = timezone.now()
    delivery.attempts += 1
    try:
        if not row.active:
            raise WebhookError('the webhook is switched off')
        url = check_url(row.url, current)
        body = json.dumps(delivery.payload, separators=(',', ':'), sort_keys=True).encode()
        stamp = int(time.time())
        status = _post(
            url,
            body,
            {
                'Content-Type': 'application/json',
                'User-Agent': 'ifinmail-webhooks/1',
                'X-Ifinmail-Event': delivery.event_type,
                'X-Ifinmail-Event-Id': delivery.event_id,
                'X-Ifinmail-Signature': sign(plugin_secrets.decrypt(row.secret), body, stamp),
            },
        )
        error = '' if 200 <= status < 300 else f'answered {status}'
    except WebhookError as exc:
        status, error = 0, str(exc)
    except Exception as exc:  # timeouts, refused connections, TLS errors
        status, error = 0, f'{type(exc).__name__}: {exc}'[:300]

    delivery.last_status_code = status or None
    delivery.last_error = error[:300]
    if not error:
        delivery.status = WebhookDelivery.DELIVERED
        delivery.delivered_at = now
        delivery.next_attempt_at = None
        row.last_success_at, row.failing_since, row.last_error = now, None, ''
        row.save(update_fields=['last_success_at', 'failing_since', 'last_error'])
    else:
        gone = status == 410
        if gone:
            row.active = False
        row.failing_since = row.failing_since or now
        row.last_error = error[:300]
        row.save(update_fields=['active', 'failing_since', 'last_error'])
        if gone or delivery.attempts >= current.max_attempts:
            delivery.status = WebhookDelivery.FAILED
            delivery.next_attempt_at = None
        else:
            wait = BACKOFF[min(delivery.attempts - 1, len(BACKOFF) - 1)]
            delivery.next_attempt_at = now + timedelta(seconds=wait)
    delivery.save(
        update_fields=[
            'attempts',
            'status',
            'next_attempt_at',
            'last_status_code',
            'last_error',
            'delivered_at',
        ]
    )
    return not error


def deliver(delivery_id: str) -> bool:
    with transaction.atomic():
        delivery = (
            WebhookDelivery.objects.select_for_update()
            .select_related('endpoint')
            .filter(pk=delivery_id, status=WebhookDelivery.PENDING)
            .first()
        )
        if delivery is None or (
            delivery.next_attempt_at and delivery.next_attempt_at > timezone.now()
        ):
            return False
    return attempt(delivery)


def sweep(limit: int = 200) -> int:
    """Deliver what is due (retries, and anything the broker missed). Runs every minute."""
    due = list(
        WebhookDelivery.objects.filter(
            status=WebhookDelivery.PENDING, next_attempt_at__lte=timezone.now()
        )
        .order_by('next_attempt_at')
        .values_list('pk', flat=True)[:limit]
    )
    for pk in due:
        deliver(str(pk))
    cutoff = timezone.now() - timedelta(days=KEEP_DAYS)
    WebhookDelivery.objects.filter(created_at__lt=cutoff).exclude(
        status=WebhookDelivery.PENDING
    ).delete()
    return len(due)


def verify(secret: str, body: bytes, header: str, *, tolerance: int = 300) -> bool:
    """How a receiver checks a signature (also what the documentation shows)."""
    try:
        parts = dict(item.split('=', 1) for item in header.split(','))
        stamp = int(parts['t'])
    except (ValueError, KeyError):
        return False
    if abs(time.time() - stamp) > tolerance:
        return False
    expected = sign(secret, body, stamp).split('v1=', 1)[1]
    return hmac.compare_digest(expected, parts.get('v1', ''))
