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
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from celery.exceptions import SoftTimeLimitExceeded
from django.core.cache import cache

from backend.apps.core.telemetry.threats import delivery as classify_delivery
from backend.apps.core.telemetry.threats.mail_log import log_dir
from backend.apps.mail.services import webhooks
from backend.apps.mail.types.events import EventType

logger = logging.getLogger('backend')

REMEMBER_SECONDS = 7 * 24 * 3600  # a message still being retried after a week has bounced
MAX_READ = 4 * 1024 * 1024  # bytes per run
FLUSH_EVERY = 500  # lines between writes of what a scan has produced
_CACHE_CHUNK = 1000  # keys per bulk cache read
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
    campaign: str = ''  # the Marketing campaign it belongs to, when it does


def _message_key(message_id: str) -> str:
    return f'apimsg:{message_id.strip("<>").lower()}'


def _queue_key(qid: str) -> str:
    return f'apiqid:{qid}'


MARKETING_ACTIVE = 'marketing:active'  # set while campaigns are being sent (see campaign_runner)


def _wanted() -> bool:
    """The log is followed for Delivery events, for Sender compliance (bounce handling) and while
    campaigns are being sent (their bounces suppress the address, whichever plugins are on)."""
    from backend.apps.mail.services import compliance

    if webhooks.policy().delivery_events or compliance.settings().enabled:
        return True
    try:
        return bool(cache.get(MARKETING_ACTIVE))
    except Exception:
        return False


def remember(message_id: str, key_prefix: str, sender: str, recipients: int) -> None:
    """Called by the send path: emit ``message.queued`` and remember the message."""
    if not _wanted():
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


def remember_many(items: Sequence[tuple[str, str, str, str]]) -> None:
    """``remember`` for many messages at once: ``(message_id, key_prefix, sender, campaign)``.

    One policy lookup, one bulk cache write and one bulk insert of the ``message.queued`` events,
    where a loop of ``remember`` calls costs a lookup, a write and about nine queries each. Used
    by the campaign runner, which sends hundreds of emails a minute.
    """
    if not items or not _wanted():
        return
    keyed = {
        _message_key(mid.strip('<>')): {
            'key_prefix': prefix,
            'sender': sender,
            'campaign': campaign,
        }
        for mid, prefix, sender, campaign in items
    }
    try:
        cache.set_many(keyed, REMEMBER_SECONDS)
    except Exception:
        logger.warning('Could not remember %d campaign messages for delivery events', len(items))
    webhooks.emit_many(
        [
            webhooks.Event(
                EventType.QUEUED,
                {
                    'message_id': mid.strip('<>'),
                    'sender': sender,
                    'recipients': 1,
                    'campaign': campaign,
                },
                key_prefix=prefix,
            )
            for mid, prefix, sender, campaign in items
        ]
    )


def _sent(mid: str) -> Sent | None:
    try:
        found = cache.get(_message_key(mid))
    except Exception:
        return None
    return _as_sent(mid, found)


_Parsed = tuple[str, re.Match[str]] | None


def _parse(line: str) -> _Parsed:
    cleanup = _CLEANUP.search(line)
    if cleanup:
        return 'cleanup', cleanup
    status = _STATUS.search(line)
    return ('status', status) if status else None


def _as_sent(mid: str, found: object) -> Sent | None:
    if not isinstance(found, dict):
        return None
    return Sent(
        mid,
        str(found.get('key_prefix', '')),
        str(found.get('sender', '')),
        str(found.get('campaign', '')),
    )


class _Direct:
    """One line at a time, straight to the cache, the counters and the webhooks."""

    def parse(self, line: str) -> _Parsed:
        return _parse(line)

    def message(self, mid: str) -> Sent | None:
        return _sent(mid)

    def queued(self, qid: str) -> str | None:
        return cache.get(_queue_key(qid))

    def link(self, qid: str, mid: str) -> None:
        cache.set(_queue_key(qid), mid, REMEMBER_SECONDS)

    def count(self, prefix: str, *, delivered: int = 0, bounced: int = 0) -> None:
        from backend.apps.mail.services import compliance

        compliance.count(prefix, delivered=delivered, bounced=bounced)

    def bounce(
        self, sender: str, recipient: str, category: str, dsn: str, reason: str, campaign: str = ''
    ) -> None:
        from backend.apps.mail.services import compliance, marketing

        if campaign:
            marketing.note_bounce(campaign, sender, recipient, category, dsn, reason)
        compliance.note_bounce(sender, recipient, category, dsn, reason)

    def emit(self, event: webhooks.Event) -> int:
        return webhooks.emit(
            event.type, event.data, key_prefix=event.key_prefix, event_id=event.event_id
        )


_DIRECT = _Direct()


def handle_line(line: str, ctx: _Direct | _Batch | None = None) -> int:
    """One Postfix log line; returns the number of events it produced.

    Without ``ctx`` every effect happens now. :func:`scan` passes a :class:`_Batch`, which looks
    keys up in bulk and collects the effects, so a whole read costs a handful of round trips.
    """
    ctx = ctx or _DIRECT
    parsed = ctx.parse(line)
    if parsed is None:
        return 0
    kind_of_line, found = parsed
    if kind_of_line == 'cleanup':
        mid = found['mid']
        if ctx.message(mid) is not None:
            ctx.link(found['qid'], mid)
        return 0
    status = found
    mid = ctx.queued(status['qid'])
    sent = ctx.message(mid) if mid else None
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
    if kind == EventType.DELIVERED:
        ctx.count(sent.key_prefix, delivered=1)
    elif kind == EventType.BOUNCED:
        ctx.count(sent.key_prefix, bounced=1)
        ctx.bounce(
            sent.sender, data['recipient'], data['category'], data['dsn'], reason, sent.campaign
        )
    # One event per (message, recipient, outcome, log line): a retry is a new deferral.
    event_id = 'evt_' + _short_hash(f'{sent.message_id}|{status["to"]}|{kind}|{line}')
    return ctx.emit(webhooks.Event(kind, data, key_prefix=sent.key_prefix, event_id=event_id))


def _short_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:24]


def _follow(path: Path | None = None) -> tuple[list[str], list[int]]:
    """``(lines, sizes)`` appended to the Postfix log since the last run (follows rotation).

    ``sizes`` is each line's length in the file, newline included, so a run that stops early can
    put the saved position back to the first line it did not handle. Records end at a newline (a
    partial last line waits for next time); a stray ``\\r`` or Unicode separator inside a record
    does not start a new one, so text in a log field cannot forge a second line.
    """
    path = path or (log_dir() / 'postfix.log')
    try:
        stat = path.stat()
    except OSError:
        return [], []
    saved = cache.get(_POSITION) or {}
    offset = int(saved.get('offset', 0)) if saved.get('inode') == stat.st_ino else 0
    if stat.st_size < offset:  # truncated in place
        offset = 0
    if offset == 0 and not saved:
        # First run: start at the end, so a fresh install does not replay old mail.
        cache.set(_POSITION, {'inode': stat.st_ino, 'offset': stat.st_size}, None)
        return [], []
    with path.open('rb') as handle:
        handle.seek(offset)
        chunk = handle.read(MAX_READ)
    # Keep a partial last line for next time.
    end = chunk.rfind(b'\n') + 1
    cache.set(_POSITION, {'inode': stat.st_ino, 'offset': offset + end}, None)
    records = chunk[:end].split(b'\n')[:-1]
    return (
        [record.decode('utf-8', 'replace').rstrip('\r') for record in records],
        [len(record) + 1 for record in records],
    )


def read_new_lines(path: Path | None = None) -> list[str]:
    """The lines appended to the Postfix log since the last run (follows rotation)."""
    return _follow(path)[0]


def _rewind(unhandled_bytes: int) -> None:
    """Put the saved position back by the bytes of lines that were read but not handled."""
    saved = cache.get(_POSITION)
    if unhandled_bytes > 0 and isinstance(saved, dict):
        offset = max(0, int(saved.get('offset', 0)) - unhandled_bytes)
        cache.set(_POSITION, {'inode': saved.get('inode'), 'offset': offset}, None)


def _get_many(keys: list[str]) -> dict[str, object]:
    found: dict[str, object] = {}
    for start in range(0, len(keys), _CACHE_CHUNK):
        found.update(cache.get_many(keys[start : start + _CACHE_CHUNK]))
    return found


class _Batch:
    """The lines of one read, handled together.

    Every cache key the lines need is fetched up front (a queue id points at a Message-ID, which
    points at the sender: two bulk reads), links made by cleanup lines in the same read are
    answered from memory, and what the lines produce (queue-id links, counters, bounces, events)
    is collected and written by :meth:`flush` in a few bulk operations. Without this one scan of a
    busy log made about 30,000 cache round trips and 40,000 queries.
    """

    def __init__(self, lines: list[str]) -> None:
        self._parsed: dict[str, _Parsed] = {}
        cleanup_mids: set[str] = set()
        status_qids: set[str] = set()
        for line in lines:
            parsed = self._parsed[line] = _parse(line)
            if parsed is None:
                continue
            if parsed[0] == 'cleanup':
                cleanup_mids.add(parsed[1]['mid'])
            else:
                status_qids.add(parsed[1]['qid'])
        raw = _get_many(
            [_message_key(mid) for mid in cleanup_mids] + [_queue_key(qid) for qid in status_qids]
        )
        self._messages: dict[str, Sent | None] = {
            mid: _as_sent(mid, raw.get(_message_key(mid))) for mid in cleanup_mids
        }
        self._queues: dict[str, str | None] = {
            qid: raw.get(_queue_key(qid))
            for qid in status_qids  # type: ignore[misc]
        }
        # Second hop: the messages that queue ids already in the cache point at.
        more = {mid for mid in self._queues.values() if mid and mid not in self._messages}
        raw = _get_many([_message_key(mid) for mid in more])
        for mid in more:
            self._messages[mid] = _as_sent(mid, raw.get(_message_key(mid)))
        self._linked: dict[str, str] = {}  # links made in this read, kept for its later lines
        self._unwritten_links: dict[str, str] = {}
        self._counts: dict[str, list[int]] = {}
        self._bounces: list[tuple[str, str, str, str, str, str]] = []
        self._events: list[webhooks.Event] = []

    def parse(self, line: str) -> _Parsed:
        return self._parsed[line] if line in self._parsed else _parse(line)

    def message(self, mid: str) -> Sent | None:
        if mid not in self._messages:
            self._messages[mid] = _sent(mid)
        return self._messages[mid]

    def queued(self, qid: str) -> str | None:
        if qid in self._linked:
            return self._linked[qid]
        if qid not in self._queues:
            self._queues[qid] = cache.get(_queue_key(qid))
        return self._queues[qid]

    def link(self, qid: str, mid: str) -> None:
        self._linked[qid] = mid
        self._unwritten_links[_queue_key(qid)] = mid

    def count(self, prefix: str, *, delivered: int = 0, bounced: int = 0) -> None:
        totals = self._counts.setdefault(prefix, [0, 0])
        totals[0] += delivered
        totals[1] += bounced

    def bounce(
        self, sender: str, recipient: str, category: str, dsn: str, reason: str, campaign: str = ''
    ) -> None:
        self._bounces.append((sender, recipient, category, dsn, reason, campaign))

    def emit(self, event: webhooks.Event) -> int:
        self._events.append(event)
        return 0  # counted when the batch is flushed

    def flush(self) -> int:
        """Write what the lines handled so far produced; returns the events queued.

        Each part is cleared once written, so a flush that is interrupted and then repeated
        (the soft time limit stops a scan part-way) does not write anything twice.
        """
        from backend.apps.mail.services import compliance, marketing

        if self._unwritten_links:
            try:
                cache.set_many(self._unwritten_links, REMEMBER_SECONDS)
            except Exception:
                logger.warning('Delivery events: queue ids could not be remembered', exc_info=True)
            self._unwritten_links = {}
        counts, self._counts = self._counts, {}
        for prefix, (delivered, bounced) in counts.items():
            try:
                compliance.count(prefix, delivered=delivered, bounced=bounced)
            except Exception:
                logger.warning('Delivery events: counters could not be updated', exc_info=True)
        bounces, self._bounces = self._bounces, []
        if bounces:
            try:
                current = compliance.settings()
                for *bounce, campaign in bounces:
                    if campaign:
                        marketing.note_bounce(campaign, *bounce)
                    compliance.note_bounce(*bounce, current=current)
            except Exception:
                logger.warning('Delivery events: bounces could not be recorded', exc_info=True)
        events, self._events = self._events, []
        return self._emit(events)

    @staticmethod
    def _emit(events: list[webhooks.Event]) -> int:
        if not events:
            return 0
        try:
            return webhooks.emit_many(events)
        except SoftTimeLimitExceeded:
            raise
        except Exception:
            # One bad event must not cost the others: fall back to one at a time, as before.
            logger.warning(
                'Delivery events: a batch failed; trying its events one at a time', exc_info=True
            )
        made = 0
        for event in events:
            try:
                made += webhooks.emit(
                    event.type, event.data, key_prefix=event.key_prefix, event_id=event.event_id
                )
            except SoftTimeLimitExceeded:
                raise
            except Exception:
                logger.warning('Delivery events: an event could not be queued', exc_info=True)
        return made


def scan() -> int:
    """Turn new log lines into events (every minute).

    Runs under a Celery time limit (``mail.tasks``). The position is saved when the lines are
    read, so when the soft limit stops a run part-way (or the bulk lookups fail) it is put back to
    the first line not yet handled: nothing is skipped, and at most the one line in flight is
    handled twice (its event id makes that a no-op for the webhook; only the sender's counters see
    it again). What the lines produced is written every ``FLUSH_EVERY`` lines and when stopping,
    before the position goes back, so a stopped run redoes at most that many lines' lookups.
    """
    if not _wanted():
        return 0
    lines, sizes = _follow()
    if not lines:
        return 0
    try:
        batch = _Batch(lines)
    except BaseException:  # the cache is down, or the soft limit: read the same lines next time
        _rewind(sum(sizes))
        raise
    produced = 0
    handled = 0
    try:
        for line in lines:
            try:
                handle_line(line, batch)
            except SoftTimeLimitExceeded:
                raise
            except Exception:
                logger.warning('Delivery events: a log line could not be handled', exc_info=True)
            handled += 1
            if handled % FLUSH_EVERY == 0:
                produced += batch.flush()
        produced += batch.flush()
    except SoftTimeLimitExceeded:
        try:
            batch.flush()  # write what the handled lines produced before the position goes back
        finally:
            _rewind(sum(sizes[handled:]))
        raise
    return produced


__all__ = ['handle_line', 'remember', 'read_new_lines', 'scan']
