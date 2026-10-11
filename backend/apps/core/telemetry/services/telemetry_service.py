"""TelemetryService — single interface for all error recording.

Best-practice pipeline:
  capture() → scrub PII → fingerprint → throttle/sample → persist (DB)
  → fallback (memory ring-buffer) on DB failure → forward to Sentry.

All model access in the telemetry app MUST go through this class
(AGENTS.md § Services Layer). Never import ErrorEvent directly outside
services/ — use ``services.models`` proxy only inside this app.
"""

from __future__ import annotations

import hashlib
import logging
import os
import traceback as tb_mod
import uuid
from contextvars import ContextVar
from datetime import timedelta
from typing import Any

from django.core.cache import cache
from django.core.paginator import Paginator
from django.db import DatabaseError, transaction
from django.utils import timezone

from backend.apps.core.telemetry.models.error_event import ErrorEvent, ErrorFingerprint
from backend.apps.core.telemetry.types import ErrorSeverity, ErrorSource, ErrorStatus

logger = logging.getLogger('backend.telemetry')

_correlation_id: ContextVar[str] = ContextVar('telemetry_correlation_id', default='')

_SEVERITY_RANK: dict[str, int] = {
    ErrorSeverity.DEBUG.value: 0,
    ErrorSeverity.INFO.value: 1,
    ErrorSeverity.WARNING.value: 2,
    ErrorSeverity.ERROR.value: 3,
    ErrorSeverity.CRITICAL.value: 4,
}

_SCRUB_KEYS = frozenset(
    {
        'password',
        'passwd',
        'secret',
        'token',
        'api_key',
        'apikey',
        'authorization',
        'cookie',
        'sessionid',
        'csrf',
        'private_key',
    }
)
_SCRUB_SUBSTRINGS = ('password', 'token', 'secret', 'authorization', 'cookie', 'session')

_THROTTLE_PER_MINUTE = 20
_MAX_MESSAGE_LEN = 2000
_MAX_TRACEBACK_LEN = 20000


def get_correlation_id() -> str:
    """Return the current correlation id, creating one if absent."""
    current = _correlation_id.get()
    if current:
        return current
    new_id = uuid.uuid4().hex[:16]
    _correlation_id.set(new_id)
    return new_id


def set_correlation_id(value: str) -> None:
    _correlation_id.set(value or '')


def scrub_value(key: str, value: Any) -> Any:
    """Redact a single value if its key looks sensitive."""
    lowered = key.lower()
    if lowered in _SCRUB_KEYS or any(s in lowered for s in _SCRUB_SUBSTRINGS):
        return '[REDACTED]'
    if isinstance(value, str) and len(value) > 2000:
        return value[:2000] + '…[truncated]'
    return value


def scrub_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Return a PII-scrubbed shallow copy of *data* (never mutates input)."""
    cleaned: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            cleaned[key] = scrub_dict(value)
        else:
            cleaned[key] = scrub_value(str(key), value)
    return cleaned


def build_fingerprint(exc_type: str, view_name: str, culled_frames: str) -> str:
    """Stable SHA256 dedup key from exception type + view + top frames."""
    raw = f'{exc_type}\n{view_name}\n{culled_frames}'.encode('utf-8', 'replace')
    return hashlib.sha256(raw).hexdigest()


def cull_traceback(exc: BaseException | None, limit: int = 5) -> str:
    """Extract the last *limit* app frames for fingerprinting (stable)."""
    if exc is None or exc.__traceback__ is None:
        return ''
    frames: list[str] = []
    extracted = tb_mod.extract_tb(exc.__traceback__)
    for frame in extracted[-limit:]:
        # Drop volatile bits (line numbers shift) — keep file tail + function.
        filename = (frame.filename or '').replace('\\', '/').split('/')[-2:]
        frames.append(f'{"//".join(filename)}:{frame.name}')
    return '|'.join(frames)


class TelemetryService:
    """Central error-telemetry service (all methods static — no instantiation)."""

    _memory_events: list[dict[str, Any]] = []
    _max_memory_events: int = 200
    _max_db_events: int = 50_000

    # ------------------------------------------------------------------
    # Capture
    # ------------------------------------------------------------------

    @staticmethod
    def capture(
        exc_or_message: BaseException | str | None,
        *,
        severity: ErrorSeverity | str = ErrorSeverity.ERROR,
        source: ErrorSource | str = ErrorSource.DJANGO,
        request: Any | None = None,
        extra: dict[str, Any] | None = None,
        correlation_id: str = '',
    ) -> dict[str, Any]:
        """Record an error. Never raises — telemetry must not break callers.

        Returns ``{'id': ..., 'fingerprint': ..., 'correlation_id': ...}``
        so handlers can correlate responses with stored rows.
        """
        try:
            return TelemetryService._capture_inner(
                exc_or_message,
                severity=str(severity),
                source=str(source),
                request=request,
                extra=extra or {},
                correlation_id=correlation_id or get_correlation_id(),
            )
        except Exception as exc:  # last-resort guard
            logger.warning('Telemetry capture failed (guarded): %s', exc)
            return {'id': '', 'fingerprint': '', 'correlation_id': get_correlation_id()}

    @staticmethod
    def capture_exception(
        exc: BaseException,
        *,
        source: ErrorSource | str = ErrorSource.DJANGO,
        request: Any | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return TelemetryService.capture(
            exc, severity=ErrorSeverity.ERROR, source=source, request=request, extra=extra
        )

    @staticmethod
    def capture_message(
        message: str,
        *,
        severity: ErrorSeverity | str = ErrorSeverity.INFO,
        source: ErrorSource | str = ErrorSource.MANUAL,
        request: Any | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return TelemetryService.capture(
            message, severity=severity, source=source, request=request, extra=extra
        )

    # ------------------------------------------------------------------
    # Queries (for logs page / API / health)
    # ------------------------------------------------------------------

    @staticmethod
    def get_recent(limit: int = 50) -> list[dict[str, Any]]:
        """Most recent events as plain dicts — DB first, memory fallback."""
        try:
            rows = list(
                ErrorEvent.objects.select_related('fingerprint').order_by('-created_at')[:limit]
            )
            if rows:
                return [TelemetryService._to_dict(e) for e in rows]
        except Exception as exc:
            logger.warning('Telemetry DB read failed, using memory buffer: %s', exc)
        return list(reversed(TelemetryService._memory_events[-limit:]))

    @staticmethod
    def get_stats() -> dict[str, Any]:
        """Aggregate counts for dashboards / health endpoints."""
        try:
            open_critical = ErrorEvent.objects.filter(
                severity__in=[ErrorSeverity.ERROR.value, ErrorSeverity.CRITICAL.value],
                resolved=False,
                created_at__gte=timezone.now() - timedelta(hours=24),
            ).count()
            total_24h = ErrorEvent.objects.filter(
                created_at__gte=timezone.now() - timedelta(hours=24)
            ).count()
            top = list(
                ErrorFingerprint.objects.order_by('-count').values(
                    'hash', 'exc_type', 'view_name', 'count', 'status', 'severity_max'
                )[:10]
            )
            return {
                'open_critical_24h': open_critical,
                'total_24h': total_24h,
                'top': top,
            }
        except Exception as exc:
            logger.warning('Telemetry stats unavailable: %s', exc)
            return {
                'open_critical_24h': 0,
                'total_24h': len(TelemetryService._memory_events),
                'top': [],
            }

    @staticmethod
    def ack_fingerprint(fingerprint_hash: str, status: ErrorStatus | str) -> bool:
        """Transition a fingerprint (ACK/RESOLVE/MUTE). Returns success."""
        try:
            updated = ErrorFingerprint.objects.filter(hash=fingerprint_hash).update(
                status=str(status), last_seen=timezone.now()
            )
            return updated > 0
        except Exception as exc:
            logger.warning('Telemetry ack failed: %s', exc)
            return False

    @staticmethod
    def list_events(
        *,
        severity: str = '',
        source: str = '',
        query: str = '',
        page: int = 1,
        page_size: int = 25,
    ) -> dict[str, Any]:
        """Paginated error events with optional filters (DB first, memory fallback)."""
        try:
            qs = ErrorEvent.objects.select_related('fingerprint').order_by('-created_at')
            if severity:
                qs = qs.filter(severity=severity)
            if source:
                qs = qs.filter(source=source)
            if query:
                qs = qs.filter(message__icontains=query[:200])
            paginator = Paginator(qs, page_size)
            page_obj = paginator.get_page(max(page, 1))
            return {
                'results': [TelemetryService._to_dict(e) for e in page_obj.object_list],
                'page': page_obj.number,
                'num_pages': paginator.num_pages,
                'total': paginator.count,
            }
        except Exception as exc:
            logger.warning('Telemetry event listing failed, using memory buffer: %s', exc)
            recent = TelemetryService.get_recent(page_size)
            return {'results': recent, 'page': 1, 'num_pages': 1, 'total': len(recent)}

    @staticmethod
    def list_fingerprints(limit: int = 25) -> list[dict[str, Any]]:
        """Top fingerprints by occurrence count (DB first, empty on failure)."""
        try:
            return list(
                ErrorFingerprint.objects.order_by('-count').values(
                    'hash', 'exc_type', 'view_name', 'count', 'status', 'severity_max'
                )[:limit]
            )
        except Exception as exc:
            logger.warning('Telemetry fingerprint listing failed: %s', exc)
            return []

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _capture_inner(
        exc_or_message: BaseException | str | None,
        *,
        severity: str,
        source: str,
        request: Any | None,
        extra: dict[str, Any],
        correlation_id: str,
    ) -> dict[str, Any]:
        if isinstance(exc_or_message, BaseException):
            exc: BaseException | None = exc_or_message
            exc_type = type(exc).__name__
            message = f'{exc_type}: {exc}'[:_MAX_MESSAGE_LEN]
            formatted_tb = ''.join(tb_mod.format_exception(exc))[:_MAX_TRACEBACK_LEN]
            frames = cull_traceback(exc)
        else:
            exc = None
            exc_type = 'Message'
            message = str(exc_or_message or '')[:_MAX_MESSAGE_LEN]
            formatted_tb = ''
            frames = message[:200]

        # Request context (duck-typed — works with HttpRequest or Ninja request).
        request_path = ''
        method = ''
        view_name = ''
        user_repr = ''
        if request is not None:
            try:
                request_path = str(getattr(request, 'path', '') or '')[:1024]
                method = str(getattr(request, 'method', '') or '')[:16]
                resolver = getattr(getattr(request, 'resolver_match', None), 'view_name', '')
                view_name = str(resolver or '')[:255]
                user = getattr(request, 'user', None)
                if user is not None and getattr(user, 'is_authenticated', False):
                    user_email = getattr(user, 'email', None)
                    user_name = getattr(user, 'username', None)
                    user_repr = str(user_email or user_name or 'user')[:255]
                else:
                    user_repr = 'anonymous'
                # Honor incoming correlation header.
                incoming = ''
                headers = getattr(request, 'headers', None)
                meta = getattr(request, 'META', {}) or {}
                if headers is not None:
                    try:
                        incoming = str(headers.get('X-Correlation-ID', '') or '')
                    except Exception:
                        incoming = ''
                if not incoming:
                    incoming = str(meta.get('HTTP_X_CORRELATION_ID', '') or '')
                if incoming:
                    correlation_id = incoming[:64]
                    set_correlation_id(correlation_id)
            except Exception:
                pass  # context extraction must never fail capture

        fingerprint_hash = build_fingerprint(exc_type, view_name or request_path, frames)

        if TelemetryService._is_throttled(fingerprint_hash):
            # Still bump the counter so storms stay visible, but skip the row.
            TelemetryService._bump_count_only(fingerprint_hash, severity)
            return {'id': '', 'fingerprint': fingerprint_hash, 'correlation_id': correlation_id}

        context = scrub_dict(
            {
                'correlation_id': correlation_id,
                'release': os.environ.get('APP_VERSION', os.environ.get('CSS_VERSION', '')),
                'environment': os.environ.get('SENTRY_ENVIRONMENT', 'production'),
                'extra': extra,
            }
        )

        # Persist synchronously when already in an atomic block/test
        # (transaction.on_commit would defer past test assertions); else defer
        # so the failing request is never slowed down.
        payload = {
            'fingerprint_hash': fingerprint_hash,
            'exc_type': exc_type,
            'severity': severity,
            'source': source,
            'message': message,
            'traceback': formatted_tb,
            'request_path': request_path,
            'method': method,
            'view_name': view_name,
            'user_repr': user_repr,
            'correlation_id': correlation_id,
            'release': str(context.get('release', '')),
            'environment': str(context.get('environment', '')),
            'context': context,
        }
        try:
            if transaction.get_autocommit():
                try:
                    transaction.on_commit(lambda: TelemetryService._persist(payload))
                except Exception:
                    TelemetryService._persist(payload)
            else:
                TelemetryService._persist(payload)
        except Exception:
            TelemetryService._persist(payload)

        # Mirror to memory buffer immediately so get_recent() works even
        # before on_commit fires or when the DB is down.
        TelemetryService._buffer_memory(payload)
        TelemetryService._forward_to_sentry(exc, message, severity, correlation_id, context)

        return {'id': '', 'fingerprint': fingerprint_hash, 'correlation_id': correlation_id}

    @staticmethod
    def _persist(payload: dict[str, Any]) -> str:
        """Write fingerprint + event rows. Returns event id or ''."""
        try:
            fingerprint, _ = ErrorFingerprint.objects.get_or_create(
                hash=payload['fingerprint_hash'],
                defaults={
                    'exc_type': payload['exc_type'],
                    'view_name': payload['view_name'],
                    'severity_max': payload['severity'],
                },
            )
            # Bump counters + escalate severity_max.
            fingerprint.count = (fingerprint.count or 0) + 1
            fingerprint.last_seen = timezone.now()
            if _SEVERITY_RANK.get(payload['severity'], 0) > _SEVERITY_RANK.get(
                fingerprint.severity_max, 0
            ):
                fingerprint.severity_max = payload['severity']
            # Un-mute on fresh occurrence after resolve? No — keep status, just count.
            fingerprint.save(update_fields=['count', 'last_seen', 'severity_max'])

            event = ErrorEvent.objects.create(
                fingerprint=fingerprint,
                severity=payload['severity'],
                source=payload['source'],
                exc_type=payload['exc_type'],
                message=payload['message'],
                traceback=payload['traceback'],
                request_path=payload['request_path'],
                method=payload['method'],
                view_name=payload['view_name'],
                user_repr=payload['user_repr'],
                correlation_id=payload['correlation_id'],
                release=payload['release'],
                environment=payload['environment'],
                context=payload['context'],
            )
            TelemetryService._maybe_purge()
            return str(event.id)
        except (DatabaseError, OSError) as exc:
            logger.warning('Telemetry DB persist failed — buffered in memory: %s', exc)
            return ''
        except Exception as exc:
            logger.warning('Telemetry persist failed: %s', exc)
            return ''

    @staticmethod
    def _bump_count_only(fingerprint_hash: str, severity: str) -> None:
        try:
            fp = ErrorFingerprint.objects.filter(hash=fingerprint_hash).first()
            if fp is None:
                return
            fp.count = (fp.count or 0) + 1
            if _SEVERITY_RANK.get(severity, 0) > _SEVERITY_RANK.get(fp.severity_max, 0):
                fp.severity_max = severity
            fp.save(update_fields=['count', 'severity_max', 'last_seen'])
        except Exception:
            pass

    @staticmethod
    def _is_throttled(fingerprint_hash: str) -> bool:
        """Per-fingerprint rate limit: >20 events/min → sample (count-only)."""
        try:
            key = f'ifinmail:telemetry:throttle:{fingerprint_hash}'
            count = cache.get(key, 0)
            if count >= _THROTTLE_PER_MINUTE:
                return True
            try:
                # add() is atomic on most backends; fall back to set().
                if hasattr(cache, 'add'):
                    cache.add(key, 0, timeout=60)
                cache.incr(key)
            except ValueError:
                cache.set(key, 1, timeout=60)
            return False
        except Exception:
            return False  # cache down → never throttle (prefer recording)

    @staticmethod
    def _buffer_memory(payload: dict[str, Any]) -> None:
        TelemetryService._memory_events.append(
            {
                'time': timezone.now().isoformat(),
                'severity': payload['severity'],
                'action': payload['exc_type'] or payload['source'],
                'detail': payload['message'],
                'service': payload['view_name'] or payload['request_path'] or payload['source'],
                'user': payload['user_repr'] or 'system',
                'correlation_id': payload['correlation_id'],
            }
        )
        if len(TelemetryService._memory_events) > TelemetryService._max_memory_events:
            TelemetryService._memory_events = TelemetryService._memory_events[
                -TelemetryService._max_memory_events :
            ]

    @staticmethod
    def _forward_to_sentry(
        exc: BaseException | None,
        message: str,
        severity: str,
        correlation_id: str,
        context: dict[str, Any],
    ) -> None:
        """Best-effort Sentry forward — failures are swallowed by design."""
        try:
            import sentry_sdk

            if not sentry_sdk.is_initialized():
                return
            with sentry_sdk.push_scope() as scope:
                scope.set_tag('correlation_id', correlation_id)
                scope.set_context('telemetry', context)
                scope.set_level(severity.lower())
                if exc is not None:
                    sentry_sdk.capture_exception(exc)
                else:
                    sentry_sdk.capture_message(message)
        except Exception:
            pass

    @staticmethod
    def _to_dict(event: ErrorEvent) -> dict[str, Any]:
        created = getattr(event, 'created_at', None)
        return {
            'id': str(event.id),
            'time': created.isoformat() if hasattr(created, 'isoformat') else '',
            'severity': event.severity,
            'action': event.exc_type or event.source,
            'detail': event.message,
            'service': event.view_name or event.request_path or event.source,
            'user': event.user_repr or 'system',
            'correlation_id': event.correlation_id,
            'fingerprint': event.fingerprint.hash if event.fingerprint_id else '',
            'source': event.source,
        }

    @staticmethod
    def _maybe_purge() -> None:
        """Delete oldest rows past the cap (cheap probabilistic check)."""
        try:
            import random

            if random.random() > 0.05:  # ~5% of writes trigger the check
                return
            total = ErrorEvent.objects.count()
            if total <= TelemetryService._max_db_events:
                return
            excess = total - TelemetryService._max_db_events
            doomed = list(
                ErrorEvent.objects.order_by('created_at').values_list('id', flat=True)[:excess]
            )
            ErrorEvent.objects.filter(id__in=doomed).delete()
            logger.info(
                'Telemetry purged %d events (cap=%d)', excess, TelemetryService._max_db_events
            )
        except Exception as exc:
            logger.warning('Telemetry purge failed: %s', exc)
