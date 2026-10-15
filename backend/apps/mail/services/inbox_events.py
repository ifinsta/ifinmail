"""Inbox webhooks: new mail in a watched mailbox becomes a ``message.received`` event.

A webhook names the mailboxes it watches. Every 30 seconds the worker asks Dovecot, over IMAP as
the console's master user, for each watched mailbox's ``UIDNEXT``; when it has moved, the new
messages are read and one event per message is queued, with the text (and HTML, when the plugin
includes it), the attachment names, and the one-time code or sign-in link already found. The
first look at a mailbox starts from "now", so turning a webhook on never replays old mail.

Who may watch what: a webhook made in the console, any mailbox (it is an administrator's
decision, recorded in the audit trail). A webhook made by an API key, only the agent inboxes
that key created, or mailboxes on this server when the key also has ``mail.manage``.
"""

from __future__ import annotations

import hashlib
import logging

from django.core.cache import cache

from backend.apps.core.plugins.services import InstallationService
from backend.apps.mail.models import WebhookEndpoint
from backend.apps.mail.services import codes, imap_reader, webhooks
from backend.apps.mail.types.events import EventType

logger = logging.getLogger('backend')

CAPABILITY = 'developer.inbox_webhooks'
MAX_MAILBOXES_PER_SCAN = 200
MAX_NEW_PER_MAILBOX = 50  # per scan; the rest follow on the next one
BODY_LIMIT = 64 * 1024  # characters of text and of HTML in one event


def include_body() -> bool:
    return InstallationService.capability_values(CAPABILITY).get('include_body', 'yes') == 'yes'


def watched() -> list[str]:
    boxes: set[str] = set()
    for row in WebhookEndpoint.objects.filter(active=True):
        if EventType.RECEIVED in row.events:
            boxes.update(row.mailboxes)
    return sorted(boxes)[:MAX_MAILBOXES_PER_SCAN]


def _state_key(mailbox: str) -> str:
    return f'inboxevents:{mailbox}'


def event_for(mailbox: str, message: imap_reader.Message, *, with_body: bool) -> dict:
    found = codes.extract(message.summary.subject, message.text, message.html)
    data = {
        'mailbox': mailbox,
        'uid': message.summary.uid,
        'message_id': message.summary.message_id,
        'from': message.summary.sender,
        'to': list(message.summary.to),
        'cc': list(message.cc),
        'delivered_to': list(message.delivered_to),
        'reply_to': message.reply_to,
        'subject': message.summary.subject,
        'date': message.summary.date,
        'size': message.summary.size,
        'snippet': imap_reader.snippet(message.text),
        'attachments': [
            {'filename': a.filename, 'content_type': a.content_type, 'size': a.size}
            for a in message.attachments
        ],
        'code': found['code'],
        'link': found['link'],
        'risk': message.headers.get('X-Agent-Risk', ''),
    }
    if with_body:
        data['text'] = message.text[:BODY_LIMIT]
        data['html'] = message.html[:BODY_LIMIT]
        data['truncated'] = len(message.text) > BODY_LIMIT or len(message.html) > BODY_LIMIT
    return data


def scan_mailbox(mailbox: str, *, with_body: bool) -> int:
    """Queue events for mail that arrived since the last look. Returns how many."""
    validity, following = imap_reader.mailbox_state(mailbox)
    saved = cache.get(_state_key(mailbox))
    if not isinstance(saved, dict) or saved.get('validity') != validity:
        # First look (or the mailbox was recreated): start from now.
        cache.set(_state_key(mailbox), {'validity': validity, 'last_uid': following - 1}, None)
        return 0
    last = int(saved.get('last_uid', 0))
    if following - 1 <= last:
        return 0
    produced = 0
    newest = last
    for summary in sorted(imap_reader.list_messages(mailbox, since_uid=last, limit=MAX_NEW_PER_MAILBOX), key=lambda s: s.uid):
        message = imap_reader.get_message(mailbox, summary.uid)
        newest = max(newest, summary.uid)
        if message is None:
            continue
        event_id = 'evt_' + hashlib.sha256(f'{mailbox}|{validity}|{summary.uid}'.encode()).hexdigest()[:24]
        produced += webhooks.emit(
            EventType.RECEIVED,
            event_for(mailbox, message, with_body=with_body),
            mailbox=mailbox,
            event_id=event_id,
        )
    cache.set(_state_key(mailbox), {'validity': validity, 'last_uid': newest}, None)
    return produced


def scan() -> int:
    """Every watched mailbox once (every 30 seconds)."""
    if not webhooks.policy().inbox_events or not imap_reader.configured():
        return 0
    with_body = include_body()
    produced = 0
    for mailbox in watched():
        try:
            produced += scan_mailbox(mailbox, with_body=with_body)
        except imap_reader.ReaderError as exc:
            logger.info('Inbox webhooks: %s skipped (%s)', mailbox, exc)
        except Exception:
            logger.warning('Inbox webhooks: %s failed', mailbox, exc_info=True)
    return produced
