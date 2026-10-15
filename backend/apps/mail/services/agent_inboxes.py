"""Agent inboxes: a real mailbox an API key creates for an AI agent, in one call.

An agent signs up for a service, waits for the verification mail and reads the code back, or
holds an email conversation of its own. The inbox is an ordinary mailbox on the domain the plugin
names (so it receives mail like any other and plus addressing works: ``agent-x7+github@``), but:

* only the key that created it can list, read or delete it (``agents.manage``), and it never
  reaches anyone else's mailbox;
* its login has a random password nobody is told, so no one signs in to it with a mail app;
* it can expire: when it does, its mail is emptied over IMAP and the mailbox removed;
* the key can send as its own inboxes (``mail.send``) without listing them as allowed senders.

Reading goes through Dovecot (``imap_reader``) as the console's master user.
"""

from __future__ import annotations

import logging
import re
import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from backend.apps.core.plugins.services import InstallationService
from backend.apps.mail.models import AgentInbox
from backend.apps.mail.services import imap_reader
from backend.apps.mail.services.mailboxes import MailboxService
from backend.apps.mail.types.provisioning import MailboxError

logger = logging.getLogger('backend')

CAPABILITY = 'developer.agent_inboxes'
MAX_WAIT_SECONDS = 25
_NAME = re.compile(r'^[a-z0-9](?:[a-z0-9._-]{0,38}[a-z0-9])?$')


class InboxError(ValueError):
    """Something the caller can fix; the message is safe to show. ``status`` is the HTTP code."""

    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class InboxSettings:
    enabled: bool
    domain: str
    max_per_key: int
    default_ttl_hours: int  # 0: kept until deleted
    quota_mb: int


def settings() -> InboxSettings:
    values = InstallationService.capability_values(CAPABILITY)

    def number(name: str, default: int) -> int:
        try:
            return int(values.get(name) or default)
        except ValueError:
            return default

    return InboxSettings(
        enabled=values.get('enabled') == 'yes',
        domain=(values.get('domain') or '').strip().lower(),
        max_per_key=number('max_per_key', 25),
        default_ttl_hours=number('default_ttl_hours', 24),
        quota_mb=number('quota_mb', 50),
    )


def _require() -> InboxSettings:
    current = settings()
    if not current.enabled:
        raise InboxError('Agent inboxes are off. Install the Agent inboxes plugin.', 403)
    if not current.domain:
        raise InboxError('The Agent inboxes plugin has no domain set.', 503)
    return current


# ------------------------------------------------------------------------------ inboxes


@transaction.atomic
def create(
    owner_prefix: str, *, name: str = '', label: str = '', ttl_hours: int | None = None
) -> AgentInbox:
    current = _require()
    if AgentInbox.objects.filter(owner_prefix=owner_prefix).count() >= current.max_per_key:
        raise InboxError(
            f'This key already has {current.max_per_key} inboxes, the most the plugin allows. '
            'Delete one first.',
            409,
        )
    local = (name or '').strip().lower()
    if local:
        if not _NAME.match(local) or '+' in local:
            raise InboxError('A name is 1-40 letters, digits, dots, dashes or underscores.')
    else:
        local = f'agent-{secrets.token_hex(4)}'
    ttl = current.default_ttl_hours if ttl_hours is None else ttl_hours
    if ttl < 0 or ttl > 24 * 365:
        raise InboxError('ttl_hours is 0 (keep) to 8760 (a year).')
    address = f'{local}@{current.domain}'
    from backend.apps.mail.models import Mailbox

    if Mailbox.objects.filter(local_part=local, domain__name=current.domain).exists():
        raise InboxError(f'{address} already exists. Choose another name.', 409)
    try:
        MailboxService.create(
            current.domain,
            local,
            secrets.token_urlsafe(32),  # nobody is told: the inbox is read through the API only
            quota_bytes=current.quota_mb * 1024 * 1024,
            is_admin=False,
            enforce_reserved=True,
        )
    except MailboxError as exc:
        raise InboxError(str(exc), 422) from exc
    return AgentInbox.objects.create(
        address=address,
        owner_prefix=owner_prefix,
        label=(label or '').strip()[:120],
        expires_at=timezone.now() + timedelta(hours=ttl) if ttl else None,
    )


def owned(owner_prefix: str) -> list[AgentInbox]:
    return list(AgentInbox.objects.filter(owner_prefix=owner_prefix))


def get(owner_prefix: str, address: str) -> AgentInbox:
    """The inbox if this key owns it; 404 otherwise (whether or not it exists)."""
    wanted = (address or '').strip().lower()
    row = AgentInbox.objects.filter(address=wanted, owner_prefix=owner_prefix).first()
    if row is None:
        raise InboxError('No inbox with that address for this key.', 404)
    return row


def owns(owner_prefix: str, address: str) -> bool:
    return bool(
        owner_prefix
        and AgentInbox.objects.filter(
            address=(address or '').strip().lower(), owner_prefix=owner_prefix
        ).exists()
    )


def delete(row: AgentInbox) -> None:
    """Empty it (so no mail stays on disk), remove the mailbox and its login, then the record."""
    try:
        imap_reader.empty(row.address)
    except imap_reader.ReaderError:
        logger.warning('Could not empty agent inbox %s before deleting it', row.address)
    try:
        MailboxService.delete(row.address)
    except MailboxError:
        logger.info('Agent inbox %s had no mailbox left', row.address)
    row.delete()


def expire(now=None) -> int:  # noqa: ANN001
    """Delete inboxes whose time is up (every few minutes)."""
    due = AgentInbox.objects.filter(expires_at__isnull=False, expires_at__lte=now or timezone.now())
    count = 0
    for row in list(due[:200]):
        delete(row)
        count += 1
    return count


# ------------------------------------------------------------------------------ mail


def _reader_error(exc: imap_reader.ReaderError) -> InboxError:
    return InboxError(str(exc), 503)


def _matches_tag(summary_to: tuple[str, ...], delivered_to: tuple[str, ...], tag: str) -> bool:
    marker = f'+{tag.lower()}@'
    return any(marker in a for a in (*summary_to, *delivered_to))


def messages(row: AgentInbox, *, since_uid: int = 0, limit: int = 50, tag: str = '') -> list[dict]:
    try:
        found = imap_reader.list_messages(row.address, since_uid=since_uid, limit=limit)
    except imap_reader.ReaderError as exc:
        raise _reader_error(exc) from exc
    if tag:
        found = [s for s in found if _matches_tag(s.to, (), tag)]
    return [s.as_dict() for s in found]


def message(row: AgentInbox, uid: int) -> dict:
    try:
        found = imap_reader.get_message(row.address, uid)
    except imap_reader.ReaderError as exc:
        raise _reader_error(exc) from exc
    if found is None:
        raise InboxError('No message with that uid in this inbox.', 404)
    return found.as_dict() | _shield(found.summary.subject, found.text, found.html)


def _shield(subject: str, text: str, html: str) -> dict:
    """``risk`` and ``safe_text`` when the Injection shield is on (``None`` otherwise)."""
    from backend.apps.mail.services import injection_shield

    current = injection_shield.settings()
    if not current.enabled:
        return {'risk': None, 'safe_text': None, 'held': False}
    risk, safe = injection_shield.analyse(subject, text, html)
    return {'risk': risk.as_dict(), 'safe_text': safe, 'held': injection_shield.held(risk, current)}


def code(row: AgentInbox, uid: int) -> dict:
    from backend.apps.mail.services import codes

    full = message(row, uid)
    if full['held']:
        raise InboxError(
            'The Injection shield holds this message (high risk of instructions planted for an '
            'agent). Read it with care, or ask an administrator.',
            409,
        )
    return {
        'uid': uid,
        'subject': full['subject'],
        'from': full['from'],
        'risk': full['risk'],
        **codes.extract(full['subject'], full['text'], full['html']),
    }


def wait(row: AgentInbox, *, since_uid: int, timeout: float, tag: str = '') -> dict | None:
    """The first message newer than ``since_uid`` (and to ``+tag`` if given), with its code and
    link already extracted; ``None`` when none arrives within ``timeout`` seconds."""
    timeout = max(0.0, min(float(timeout), MAX_WAIT_SECONDS))
    deadline = timezone.now() + timedelta(seconds=timeout)
    cursor = since_uid
    while True:
        remaining = (deadline - timezone.now()).total_seconds()
        try:
            found = imap_reader.wait_for(row.address, since_uid=cursor, timeout=max(remaining, 0))
        except imap_reader.ReaderError as exc:
            raise _reader_error(exc) from exc
        for summary in sorted(found, key=lambda s: s.uid):
            cursor = max(cursor, summary.uid)
            if tag and not _matches_tag(summary.to, (), tag):
                full = message(row, summary.uid)
                if not _matches_tag(tuple(full['to']), tuple(full['delivered_to']), tag):
                    continue
            try:
                return code(row, summary.uid) | {'message': summary.as_dict()}
            except InboxError as exc:
                if exc.status == 409:  # held by the Injection shield: not for agents
                    continue
                raise
        if timezone.now() >= deadline:
            return None


def delete_message(row: AgentInbox, uid: int) -> None:
    try:
        imap_reader.delete_message(row.address, uid)
    except imap_reader.ReaderError as exc:
        raise _reader_error(exc) from exc
