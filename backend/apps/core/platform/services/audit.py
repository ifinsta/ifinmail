"""Audit trail service.

Persists audit events to the database via the AuditEvent model with
an in-memory fallback when the database is unavailable.  Keeps the
last 200 events in memory for fast dashboard access via get_recent().

Retention is time-based (``AUDIT_RETENTION_DAYS``, default 365, minimum 30).
Each persisted event stores the SHA-256 of its own fields plus the previous
event's hash, so an edited or removed row inside the retention window breaks
the chain and ``verify_chain`` reports where.  The chain proves *integrity of
what is stored*; it cannot show that the newest rows were never deleted, so
the head hash is included in every export for pinning off-host.
"""

import hashlib
import json
import logging
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger('backend')

DEFAULT_RETENTION_DAYS = 365
# Stored severities are free text; these are the ones the console and its services write.
_ERROR_SEVERITIES = frozenset({'err', 'error', 'critical', 'crit', 'fatal'})
_WARNING_SEVERITIES = frozenset({'warn', 'warning'})
MIN_RETENTION_DAYS = 30
# Two writers can race for the same sequence number; the unique constraint
# makes the loser retry instead of forking the chain.
_CHAIN_RETRIES = 5

# Lazy-import to avoid circular imports when models are not yet registered.
_AuditEvent = None


def _get_audit_model() -> Any:
    """Return the AuditEvent model class, importing it on first access."""
    global _AuditEvent
    if _AuditEvent is None:
        from backend.apps.core.platform.models import AuditEvent

        _AuditEvent = AuditEvent
    return _AuditEvent


class AuditService:
    """Central audit-trail service.

    In-memory buffer provides fast reads for dashboards; the database
    table provides durable, queryable long-term storage.
    """

    _events: list[dict] = []
    _max_memory_events: int = 200

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def record(
        cls,
        action: str,
        user: str | None = None,
        detail: str = '',
        severity: str = 'info',
    ) -> None:
        """Record an audit event.

        Persists to the database first.  If the database is unreachable
        the event is still kept in the in-memory ring buffer so that
        dashboards are not left empty.
        """
        event_data = {
            'user': user or 'system',
            'action': action,
            'detail': detail,
            'severity': severity,
        }

        db_saved = cls._persist_to_db(event_data)

        # Always mirror to the in-memory buffer for fast reads.
        memory_event = {
            'time': datetime.now(UTC).isoformat(),
            **event_data,
        }
        cls._events.append(memory_event)
        if len(cls._events) > cls._max_memory_events:
            cls._events = cls._events[-cls._max_memory_events :]

        log_flag = '[db]' if db_saved else '[mem]'
        logger.info(
            'AUDIT %s: %s by %s — %s',
            log_flag,
            action,
            event_data['user'],
            detail,
        )

    @classmethod
    def get_recent(cls, limit: int = 50) -> list[dict]:
        """Return the *limit* most recent events from the in-memory buffer or database."""
        if not cls._events:
            try:
                audit_event = _get_audit_model()
                db_events = audit_event.objects.all()[:limit]
                cls._events = [
                    {
                        'time': e.time.isoformat() if hasattr(e.time, 'isoformat') else str(e.time),
                        'user': e.user,
                        'action': e.action,
                        'detail': e.detail,
                        'severity': e.severity,
                    }
                    for e in reversed(db_events)
                ]
            except Exception as exc:
                logger.warning('AUDIT: Failed to fetch recent events from DB — %s', exc)
        return cls._events[-limit:]

    # ------------------------------------------------------------------
    # Queries (single interface for all AuditEvent reads — cross-app code
    # must use these, never ``backend.apps.core.platform.models`` directly).
    # ------------------------------------------------------------------

    @classmethod
    def _memory_search(cls, action: str | None = None, **filters: object) -> list[dict]:
        def match(event: dict) -> bool:
            if action is not None and event.get('action') != action:
                return False
            return all(event.get(key) == value for key, value in filters.items())

        return [e for e in cls._events if match(e)]

    @classmethod
    def has(cls, action: str, **filters: object) -> bool:
        """True when at least one event matches (database first, memory fallback)."""
        try:
            audit_event = _get_audit_model()
            return audit_event.objects.filter(action=action, **filters).exists()
        except Exception:
            return bool(cls._memory_search(action, **filters))

    @classmethod
    def count(cls, action: str | None = None, **filters: object) -> int:
        """Number of matching events (database first, memory fallback)."""
        try:
            audit_event = _get_audit_model()
            if action is None:
                return audit_event.objects.filter(**filters).count()
            return audit_event.objects.filter(action=action, **filters).count()
        except Exception:
            return len(cls._memory_search(action, **filters))

    @classmethod
    def details(cls, limit: int = 200) -> list[str]:
        """Most recent event details, newest first (for content assertions)."""
        try:
            audit_event = _get_audit_model()
            return list(
                audit_event.objects.order_by('-time').values_list('detail', flat=True)[:limit]
            )
        except Exception:
            return [str(e.get('detail', '')) for e in reversed(cls._events[-limit:])]

    @staticmethod
    def level_of(severity: str) -> str:
        """Display level of a stored severity: ``error``, ``warning`` or ``info``."""
        lowered = (severity or '').lower()
        if lowered in _ERROR_SEVERITIES:
            return 'error'
        if lowered in _WARNING_SEVERITIES:
            return 'warning'
        return 'info'

    @classmethod
    def _filtered(cls, rows: Any, level: str, q: str, since: datetime | None, after: Any) -> Any:
        from django.db.models import Q

        level = (level or '').lower()
        if level == 'error':
            rows = rows.filter(severity__in=sorted(_ERROR_SEVERITIES))
        elif level == 'warning':
            rows = rows.filter(severity__in=sorted(_WARNING_SEVERITIES))
        elif level == 'info':
            rows = rows.exclude(severity__in=sorted(_ERROR_SEVERITIES | _WARNING_SEVERITIES))
        if q:
            term = q[:100]
            rows = rows.filter(
                Q(action__icontains=term) | Q(detail__icontains=term) | Q(user__icontains=term)
            )
        if since is not None:
            rows = rows.filter(time__gte=since)
        if after is not None:
            rows = rows.filter(time__gt=after)
        return rows

    @staticmethod
    def _row(event: Any) -> dict[str, Any]:
        return {
            'id': str(event.pk),
            'seq': event.seq,
            'time': event.time.astimezone(UTC).isoformat(timespec='microseconds'),
            'user': event.user,
            'action': event.action,
            'detail': event.detail,
            'severity': event.severity,
            'level': AuditService.level_of(event.severity),
        }

    @classmethod
    def search(
        cls,
        *,
        level: str = '',
        q: str = '',
        since: datetime | None = None,
        after: datetime | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> dict[str, Any]:
        """One page of events, newest first, straight from the database.

        ``level`` is ``error``/``warning``/``info`` (any case), ``q`` matches the action, the
        detail and the user, ``since`` bounds the period, and ``after`` returns only events
        newer than that instant (live view). Returns ``rows``, ``total``, ``page``, ``pages``.
        """
        page_size = max(1, min(page_size, 200))
        try:
            rows = cls._filtered(_get_audit_model().objects.all(), level, q, since, after)
            total = rows.count()
            pages = max(1, -(-total // page_size))
            page = min(max(int(page), 1), pages)
            chunk = rows.order_by('-time', '-seq')[(page - 1) * page_size : page * page_size]
            return {
                'rows': [cls._row(e) for e in chunk],
                'total': total,
                'page': page,
                'pages': pages,
            }
        except Exception as exc:
            logger.warning('AUDIT: search fell back to the memory buffer — %s', exc)
            wanted = (level or '').lower()
            term = (q or '').lower()
            matched = []
            for event in reversed(cls._events):
                fields = (event.get('action', ''), event.get('detail', ''), event.get('user', ''))
                text = ' '.join(str(part) for part in fields)
                shown = cls.level_of(event.get('severity', ''))
                if (wanted and shown != wanted) or (term and term not in text.lower()):
                    continue
                matched.append({**event, 'id': '', 'seq': None, 'level': shown})
            return {'rows': matched[:page_size], 'total': len(matched), 'page': 1, 'pages': 1}

    @classmethod
    def level_counts(cls, since: datetime | None = None) -> dict[str, int]:
        """Events per display level (``error``/``warning``/``info``) since an instant."""
        counts = {'error': 0, 'warning': 0, 'info': 0}
        try:
            from django.db.models import Count

            rows = _get_audit_model().objects.all()
            if since is not None:
                rows = rows.filter(time__gte=since)
            for item in rows.values('severity').annotate(n=Count('pk')):
                counts[cls.level_of(item['severity'])] += item['n']
        except Exception as exc:
            logger.warning('AUDIT: level counts unavailable — %s', exc)
        return counts

    @classmethod
    def get_for_subject(cls, subject: str, limit: int = 50) -> list[dict]:
        """Events involving ``subject`` as actor or target, newest first."""
        try:
            from django.db.models import Q

            audit_event = _get_audit_model()
            rows = audit_event.objects.filter(Q(user=subject) | Q(detail=subject)).order_by(
                '-time'
            )[:limit]
            return [
                {
                    'time': e.time.isoformat() if hasattr(e.time, 'isoformat') else str(e.time),
                    'user': e.user,
                    'action': e.action,
                    'detail': e.detail,
                    'severity': e.severity,
                }
                for e in rows
            ]
        except Exception:
            matched = [
                e for e in cls._events if e.get('user') == subject or e.get('detail') == subject
            ]
            return list(reversed(matched[-limit:]))

    # ------------------------------------------------------------------
    # Retention, integrity and export
    # ------------------------------------------------------------------

    @staticmethod
    def retention_days() -> int:
        """Days an event is kept (``AUDIT_RETENTION_DAYS``; never below the minimum)."""
        try:
            days = int(os.environ.get('AUDIT_RETENTION_DAYS', str(DEFAULT_RETENTION_DAYS)))
        except ValueError:
            days = DEFAULT_RETENTION_DAYS
        return max(days, MIN_RETENTION_DAYS)

    @classmethod
    def purge_expired(cls, now: datetime | None = None) -> tuple[int, int]:
        """Delete events older than the retention window. Returns ``(deleted, before)``.

        The newest chained event is always kept so the chain keeps its head, and
        nothing inside the window can be removed through this call.
        """
        from django.utils import timezone

        audit_event = _get_audit_model()
        total_before = audit_event.objects.count()
        cutoff = (now or timezone.now()) - timedelta(days=cls.retention_days())
        expired = audit_event.objects.filter(time__lt=cutoff)
        head = audit_event.objects.filter(seq__isnull=False).order_by('-seq').first()
        if head is not None:
            expired = expired.exclude(pk=head.pk)
        deleted, _ = expired.delete()
        return deleted, total_before

    @staticmethod
    def digest(
        seq: int, when: datetime, user: str, action: str, detail: str, severity: str, prev: str
    ) -> str:
        """SHA-256 over a canonical encoding of one event and its predecessor's hash."""
        payload = json.dumps(
            [seq, when.astimezone(UTC).isoformat(timespec='microseconds'), user, action]
            + [detail, severity, prev],
            separators=(',', ':'),
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode('utf-8')).hexdigest()

    @classmethod
    def verify_chain(cls) -> dict[str, Any]:
        """Walk the chain oldest to newest.

        Returns ``{'ok', 'checked', 'head_seq', 'head_hash', 'error'}``. ``error`` names
        the first sequence number that fails and why (``hash`` = fields were changed,
        ``link`` = a row between two others was removed or reordered).
        """
        audit_event = _get_audit_model()
        rows = audit_event.objects.filter(seq__isnull=False).order_by('seq').iterator()
        checked, prev_seq, prev_hash = 0, None, ''
        for row in rows:
            expected = cls.digest(
                row.seq, row.time, row.user, row.action, row.detail, row.severity, row.prev_hash
            )
            if expected != row.entry_hash:
                return cls._chain_result(False, checked, prev_seq, prev_hash, row.seq, 'hash')
            # The oldest retained row is the anchor: its predecessor was purged.
            if prev_seq is not None and (row.prev_hash != prev_hash or row.seq != prev_seq + 1):
                return cls._chain_result(False, checked, prev_seq, prev_hash, row.seq, 'link')
            checked, prev_seq, prev_hash = checked + 1, row.seq, row.entry_hash
        return cls._chain_result(True, checked, prev_seq, prev_hash, None, '')

    @staticmethod
    def _chain_result(
        ok: bool, checked: int, head_seq: int | None, head_hash: str, bad: int | None, why: str
    ) -> dict[str, Any]:
        error = None if ok else {'seq': bad, 'reason': why}
        return {
            'ok': ok,
            'checked': checked,
            'head_seq': head_seq,
            'head_hash': head_hash,
            'error': error,
        }

    @classmethod
    def export_rows(
        cls, severity: str = '', q: str = '', since: datetime | None = None
    ) -> Iterator[dict[str, Any]]:
        """Retained events (all, or those matching the filters), oldest first, from the database."""
        rows = cls._filtered(_get_audit_model().objects.all(), severity, q, since, None)
        for row in rows.order_by('time', 'seq').iterator():
            yield {
                'seq': row.seq,
                'time': row.time.astimezone(UTC).isoformat(timespec='microseconds'),
                'user': row.user,
                'action': row.action,
                'detail': row.detail,
                'severity': row.severity,
                'prev_hash': row.prev_hash,
                'entry_hash': row.entry_hash,
            }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @classmethod
    def _persist_to_db(cls, event_data: dict) -> bool:
        """Append one event to the hash chain.

        Returns ``True`` on success, ``False`` when the database is not
        available (the caller still keeps the event in memory).
        """
        try:
            from django.db import IntegrityError, transaction
            from django.utils import timezone

            audit_event = _get_audit_model()
            for _attempt in range(_CHAIN_RETRIES):
                try:
                    with transaction.atomic():
                        head = (
                            audit_event.objects.filter(seq__isnull=False).order_by('-seq').first()
                        )
                        seq = head.seq + 1 if head else 1
                        prev = head.entry_hash if head else ''
                        now = timezone.now()
                        entry = cls.digest(
                            seq,
                            now,
                            event_data['user'],
                            event_data['action'],
                            event_data['detail'],
                            event_data['severity'],
                            prev,
                        )
                        audit_event.objects.create(
                            time=now, seq=seq, prev_hash=prev, entry_hash=entry, **event_data
                        )
                    return True
                except IntegrityError:
                    continue
            logger.warning('AUDIT: chain write lost the sequence race %d times', _CHAIN_RETRIES)
            return False
        except Exception as exc:
            logger.warning('AUDIT: DB persist failed — %s', exc)
            return False
