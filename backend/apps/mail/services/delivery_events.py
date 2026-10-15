"""Delivery Events: what became of each message sent through the API, as webhook events.

``POST /api/v1/messages`` remembers the Message-ID it gave the message (and which key sent it)
and emits ``message.queued`` at once. A worker job, every minute, reads the new lines of the
Postfix log: the cleanup line ties a queue id to that Message-ID, and each status line for the
queue id becomes ``message.delivered``, ``message.deferred`` or ``message.bounced`` for one
recipient, with the receiving server's reason scrubbed of addresses and classified like the
Delivery report does.

Only mail sent through the API produces events (people's own mail never does), and an event
carries what the sender already knows: its message id, sender, the recipient, the outcome.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from django.core.cache import cache

from backend.apps.core.telemetry.threats import delivery as classify_delivery
from backend.apps.core.telemetry.threats.mail_log import log_dir
from backend.apps.mail.services import webhooks
from backend.apps.mail.types.events import EventType

logger = logging.getLogger('backend')

REMEMBER_SECONDS = 7 * 24 * 3600  # a message still being retried after a week has bounced
MAX_READ = 4 * 1024 * 1024  # bytes per run
_POSITION = 'deliveryevents:position'
_CLEANUP = re.compile(
    r'postfix/(?:\w+/)?cleanup\[\d+\]: (?P<qid>[0-9A-Za-z]+): message-id=<(?P<mid>[^>]+)>'
)
_STATUS = re.compile(
    r'postfix/(?:\w+/)?(?:smtp|lmtp|local|virtual)\[\d+\]: (?P<qid>[0-9A-Za-z]+): '
    r'to=<(?P<to>[^>]*)>, (?:orig_to=<[^>]*>, )?relay=(?P<relay>[^,]*), .*?'
    r'(?:dsn=(?P<dsn>\d\.\d{1,3}\.\d{1,3}), )?status=(?P<status>sent|deferred|bounced)'
    r'(?: \((?P<detail>.*)\))?'
)
_OUTCOME = {
    'sent': EventType.DELIVERED,
    'deferred': EventType.DEFERRED,
    'bounced': EventType.BOUNCED,
}


@dataclass(frozen=True)
class Sent:
    message_id: str
    key_prefix: str
    sender: str


def _message_key(message_id: str) -> str:
    return f'apimsg:{message_id.strip("<>").lower()}'


def _queue_key(qid: str) -> str:
    return f'apiqid:{qid}'


def remember(message_id: str, key_prefix: str, sender: str, recipients: int) -> None:
    """Called by the send path: emit ``message.queued`` and remember the message."""
    if not webhooks.policy().delivery_events:
        return
    mid = message_id.strip('<>')
    try:
        cache.set(
            _message_key(mid),
            {'key_prefix': key_prefix, 'sender': sender},
            REMEMBER_SECONDS,
        )
    except Exception:
        logger.warning('Could not remember API message %s for delivery events', mid)
    webhooks.emit(
        EventType.QUEUED,
        {'message_id': mid, 'sender': sender, 'recipients': recipients},
        key_prefix=key_prefix,
    )


def _sent(mid: str) -> Sent | None:
    try:
        found = cache.get(_message_key(mid))
    except Exception:
        return None
    if not isinstance(found, dict):
        return None
    return Sent(mid, str(found.get('key_prefix', '')), str(found.get('sender', '')))


def handle_line(line: str) -> int:
    """One Postfix log line; returns the number of events it produced."""
    cleanup = _CLEANUP.search(line)
    if cleanup:
        mid = cleanup['mid']
        if _sent(mid) is not None:
            cache.set(_queue_key(cleanup['qid']), mid, REMEMBER_SECONDS)
        return 0
    status = _STATUS.search(line)
    if not status:
        return 0
    mid = cache.get(_queue_key(status['qid']))
    sent = _sent(mid) if mid else None
    if sent is None:
        return 0
    kind = _OUTCOME[status['status']]
    relay = status['relay']
    if kind == EventType.DELIVERED and relay.startswith(('127.0.0.1', 'localhost')):
        return 0  # the hop to the local filter, not a delivery
    reason = classify_delivery.scrub(status['detail'] or '')
    data = {
        'message_id': sent.message_id,
        'sender': sent.sender,
        'recipient': status['to'].lower(),
        'dsn': status['dsn'] or '',
        'reason': reason,
    }
    if kind != EventType.DELIVERED:
        data['category'] = classify_delivery.classify(status['dsn'] or '', reason)
    # One event per (message, recipient, outcome, log line): a retry is a new deferral.
    event_id = 'evt_' + _short_hash(f'{sent.message_id}|{status["to"]}|{kind}|{line}')
    return webhooks.emit(kind, data, key_prefix=sent.key_prefix, event_id=event_id)


def _short_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:24]


def read_new_lines(path: Path | None = None) -> list[str]:
    """The lines appended to the Postfix log since the last run (follows rotation)."""
    path = path or (log_dir() / 'postfix.log')
    try:
        stat = path.stat()
    except OSError:
        return []
    saved = cache.get(_POSITION) or {}
    offset = int(saved.get('offset', 0)) if saved.get('inode') == stat.st_ino else 0
    if stat.st_size < offset:  # truncated in place
        offset = 0
    if offset == 0 and not saved:
        # First run: start at the end, so a fresh install does not replay old mail.
        cache.set(_POSITION, {'inode': stat.st_ino, 'offset': stat.st_size}, None)
        return []
    with path.open('rb') as handle:
        handle.seek(offset)
        chunk = handle.read(MAX_READ)
    # Keep a partial last line for next time.
    end = chunk.rfind(b'\n') + 1
    cache.set(_POSITION, {'inode': stat.st_ino, 'offset': offset + end}, None)
    return chunk[:end].decode('utf-8', 'replace').splitlines()


def scan() -> int:
    """Turn new log lines into events (every minute)."""
    if not webhooks.policy().delivery_events:
        return 0
    produced = 0
    for line in read_new_lines():
        try:
            produced += handle_line(line)
        except Exception:
            logger.warning('Delivery events: a log line could not be handled', exc_info=True)
    return produced


__all__ = ['handle_line', 'remember', 'read_new_lines', 'scan']
