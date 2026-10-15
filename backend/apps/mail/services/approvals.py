"""Human approval: mail an agent (or any API key) sends waits until a person approves it.

Agents act fast and can be misled (see the Injection shield). For outgoing mail the safest
control is a person in the loop where it matters: the plugin holds a message when its rule says
so, keeps it, and sends it only after an administrator approves it, in the console or with a key
that has ``mail.manage``. A key can never approve its own messages.

Rules (the plugin's choice):

* ``all``: every message;
* ``external``: a message with a recipient outside the domains hosted here;
* ``first_contact``: a message to someone this sender has not written to before.

They apply to keys that manage agent inboxes (``agents.manage``) or, if the plugin says so, to
every key. A held message answers ``202`` with ``"status": "pending_approval"`` and an id the
sender can poll. Approving runs every check of a normal send again (the key must still exist and
be allowed), so a message never leaves with rights its key has since lost. Unanswered messages
expire after the plugin's number of hours.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import timedelta

from django.core.cache import cache
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from backend.apps.core.plugins.services import InstallationService
from backend.apps.domains.models import Domain
from backend.apps.mail.models import PendingMessage

logger = logging.getLogger('backend')

CAPABILITY = 'developer.approvals'
_CONTACTS_TTL = 400 * 24 * 3600
_NOTIFY_EVERY = 600  # at most one "waiting for approval" email per 10 minutes


class ApprovalError(ValueError):
    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class ApprovalSettings:
    enabled: bool
    rule: str  # all | external | first_contact
    applies_to: str  # agents | all
    expire_hours: int


def settings() -> ApprovalSettings:
    values = InstallationService.capability_values(CAPABILITY)
    try:
        hours = int(values.get('expire_hours') or 24)
    except ValueError:
        hours = 24
    return ApprovalSettings(
        enabled=values.get('enabled') == 'yes',
        rule=values.get('rule') or 'all',
        applies_to=values.get('applies_to') or 'agents',
        expire_hours=hours,
    )


# ------------------------------------------------------------------------------ the rule


def _contact_key(sender: str) -> str:
    return f'apicontacts:{hashlib.sha256(sender.encode()).hexdigest()[:24]}'


def _h(recipient: str) -> str:
    return hashlib.sha256(recipient.encode()).hexdigest()[:20]


def remember_contacts(sender: str, recipients: list[str]) -> None:
    """After a message really left: these recipients are no longer a first contact."""
    try:
        known = set(cache.get(_contact_key(sender)) or [])
        known.update(_h(r) for r in recipients)
        cache.set(_contact_key(sender), sorted(known)[-5000:], _CONTACTS_TTL)
    except Exception:
        logger.warning('Could not remember the contacts of %s', sender)


def reason_to_hold(*, agent_key: bool, sender: str, recipients: list[str]) -> str:
    """Why this message must wait, or ``''`` when it may go now."""
    current = settings()
    if not current.enabled or (current.applies_to == 'agents' and not agent_key):
        return ''
    if current.rule == 'all':
        return 'Every message from this key needs approval.'
    if current.rule == 'external':
        hosted = set(
            Domain.objects.filter(name__in={r.rpartition('@')[2] for r in recipients}).values_list(
                'name', flat=True
            )
        )
        outside = sorted({r for r in recipients if r.rpartition('@')[2] not in hosted})
        return f'Recipients outside this server: {", ".join(outside[:5])}' if outside else ''
    if current.rule == 'first_contact':
        try:
            known = set(cache.get(_contact_key(sender)) or [])
        except Exception:
            known = set()
        new = [r for r in recipients if _h(r) not in known]
        return f'First message to: {", ".join(new[:5])}' if new else ''
    return ''


# ------------------------------------------------------------------------------ holding


def hold(*, key_prefix: str, key_name: str, request, reason: str) -> PendingMessage:  # noqa: ANN001
    from backend.apps.mail.services.messages import address

    row = PendingMessage.objects.create(
        key_prefix=key_prefix,
        key_name=key_name[:64],
        sender=address(request.sender),
        to=[address(a) for a in request.to],
        cc=[address(a) for a in request.cc],
        bcc=[address(a) for a in request.bcc],
        reply_to=address(request.reply_to) if request.reply_to else '',
        subject=(request.subject or '').strip()[:998],
        text=request.text or '',
        html=request.html or '',
        reason=reason[:200],
    )
    _notify(row)
    return row


def _notify(row: PendingMessage) -> None:
    try:
        if not cache.add('approvals:notified', 1, _NOTIFY_EVERY):
            return
    except Exception:
        return
    from backend.apps.mail.services.containment import _recipients_of_alerts
    from backend.config import site_url

    recipients = _recipients_of_alerts(())
    if not recipients:
        return
    link = site_url.absolute_url(None, 'accounts:approvals')
    try:
        send_mail(
            'A message is waiting for approval',
            f'{row.key_name or "An API key"} wants to send "{row.subject[:120]}" from {row.sender} '
            f'to {len(row.recipients)} recipient(s).\nReason it was held: {row.reason}\n\n'
            f'Approve or reject it here: {link}\n',
            None,
            recipients,
            fail_silently=False,
        )
    except Exception:
        logger.warning('Could not tell administrators about a held message', exc_info=True)


def get(pending_id: str) -> PendingMessage | None:
    try:
        return PendingMessage.objects.filter(pk=pending_id).first()
    except (ValueError, TypeError):
        return None


def listing(*, key_prefix: str | None, status: str = '') -> list[PendingMessage]:
    rows = PendingMessage.objects.all()
    if key_prefix is not None:
        rows = rows.filter(key_prefix=key_prefix)
    if status:
        rows = rows.filter(status=status)
    return list(rows[:500])


# ------------------------------------------------------------------------------ deciding


@transaction.atomic
def approve(pending_id: str, *, actor: str, actor_prefix: str = '', note: str = '') -> PendingMessage:
    """Send it now, with every check of a normal send. Raises ``ApprovalError``."""
    from backend.apps.accounts.models import APIToken
    from backend.apps.accounts.services.tokens import key_id
    from backend.apps.mail.services.messages import (
        MessageService,
        SendingKey,
        SendRefused,
        SendRequest,
    )

    row = PendingMessage.objects.select_for_update().filter(pk=pending_id).first()
    if row is None:
        raise ApprovalError('No such message.', 404)
    if row.status != PendingMessage.PENDING:
        raise ApprovalError(f'This message is already {row.status}.')
    if actor_prefix and actor_prefix == row.key_prefix:
        raise ApprovalError('A key cannot approve its own messages.', 403)
    key = APIToken.objects.filter(prefix=row.key_prefix).first()
    if key is None or (key.expires_at and key.expires_at <= timezone.now()):
        return _decide(row, PendingMessage.FAILED, actor, 'The key that sent it no longer exists.')
    request = SendRequest(
        sender=row.sender,
        to=tuple(row.to),
        cc=tuple(row.cc),
        bcc=tuple(row.bcc),
        reply_to=row.reply_to or None,
        subject=row.subject,
        text=row.text or None,
        html=row.html or None,
    )
    sending = SendingKey(
        key_id=key_id(key.prefix),
        allowed_senders=tuple(key.allowed_senders or ()),
        daily_recipients=key.send_limit_per_day,
        sandbox=key.sandbox,
        prefix=key.prefix,
        name=key.name,
        agent='agents.manage' in (key.scopes or []),
        approved=True,
    )
    try:
        receipt = MessageService.send(request, sending)
    except SendRefused as exc:
        return _decide(row, PendingMessage.FAILED, actor, exc.message)
    row.message_id = receipt.message_id
    from backend.apps.mail.services import delivery_events

    try:
        delivery_events.remember(receipt.message_id, key.prefix, row.sender, receipt.recipients)
    except Exception:
        logger.warning('Could not record delivery events for an approved message')
    return _decide(row, PendingMessage.SENT, actor, note)


def reject(pending_id: str, *, actor: str, actor_prefix: str = '', note: str = '') -> PendingMessage:
    row = get(pending_id)
    if row is None:
        raise ApprovalError('No such message.', 404)
    if row.status != PendingMessage.PENDING:
        raise ApprovalError(f'This message is already {row.status}.')
    if actor_prefix and actor_prefix == row.key_prefix:
        raise ApprovalError('A key cannot decide on its own messages.', 403)
    return _decide(row, PendingMessage.REJECTED, actor, note)


def _decide(row: PendingMessage, status: str, actor: str, note: str) -> PendingMessage:
    from backend.apps.core.platform.services.audit import AuditService

    row.status = status
    row.decided_at = timezone.now()
    row.decided_by = actor[:255]
    row.note = (note or '')[:300]
    row.save(update_fields=['status', 'decided_at', 'decided_by', 'note', 'message_id'])
    AuditService.record(
        action=f'approval_{status}',
        user=actor or None,
        detail=f'{row.sender} -> {len(row.recipients)} recipient(s): {row.subject[:80]}',
    )
    return row


def expire(now=None) -> int:  # noqa: ANN001
    hours = settings().expire_hours
    cutoff = (now or timezone.now()) - timedelta(hours=hours)
    return PendingMessage.objects.filter(status=PendingMessage.PENDING, created_at__lt=cutoff).update(
        status=PendingMessage.EXPIRED, decided_at=timezone.now(), decided_by='expired'
    )
