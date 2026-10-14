"""Run one pass: read, detect, keep the slim version, discard the rest, tell someone if it matters.

``run()`` is idempotent and cheap to repeat: the access log is read statelessly over the last
hour, findings are keyed so the same scanner is the same finding, and each UTC hour has one
digest row that later passes update. ``compact()`` is the discarding.
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from django.core.mail import send_mail
from django.db import transaction

from backend.apps.core.platform.services.audit import AuditService
from backend.apps.core.telemetry.models import ErrorEvent, ThreatDigest, ThreatFinding

from . import (
    access_log,
    adaptive,
    collect,
    delivery,
    mail_log,
    mail_rules,
    rollup,
    rules,
    summarize,
)
from .classify import clean, probe_class
from .types import Action, Finding, Severity, WindowSummary

logger = logging.getLogger('backend.telemetry')

WINDOW_MINUTES = 60
AUTH_HOURS = 24
RESOLVE_AFTER = timedelta(hours=24)  # a finding not seen for this long is resolved
ALERT_AT = Severity.HIGH
ALERT_EVERY = timedelta(hours=24)  # per finding
SUMMARY_EVERY = timedelta(minutes=30)  # at most one model call this often
KEEP_QUIET_DIGESTS = timedelta(days=28)  # a quiet hour is kept this long: it is the baseline
KEEP_DIGESTS = timedelta(days=90)
KEEP_RESOLVED = timedelta(days=30)
NOISE_AGE = timedelta(hours=48)  # INFO and WARNING error events are discarded after this


@dataclass
class DigestResult:
    summary: WindowSummary
    findings: list[Finding]
    digest: ThreatDigest | None
    log_available: bool
    alerted: int = 0
    summarised: bool = False


def enabled() -> bool:
    return os.environ.get('THREAT_DIGEST_ENABLED', '1').lower() not in ('0', 'false', 'no')


def _as_dict(summary: WindowSummary) -> dict[str, Any]:
    body = asdict(summary)
    body['start'] = summary.start.isoformat()
    body['end'] = summary.end.isoformat()
    return body


def _actions(items: list[Action]) -> list[dict[str, str]]:
    return [{'label': a.label, 'where': a.where, 'detail': a.detail} for a in items]


def _correlate(findings: list[Finding]) -> list[str]:
    """Sentences that join findings about the same network: one actor, several behaviours."""
    by_subject: dict[str, list[Finding]] = defaultdict(list)
    for finding in findings:
        if '/' in finding.subject:
            by_subject[finding.subject].append(finding)
    notes = []
    for subject, items in by_subject.items():
        kinds = sorted({f.kind for f in items})
        if len(kinds) >= 2:
            notes.append(
                f'{subject} shows {len(kinds)} behaviours at once '
                f'({", ".join(k.replace("_", " ") for k in kinds)}): one actor, not noise.'
            )
    return notes


def _probe_errors(requests: list[Any]) -> list[Finding]:
    """Probes whose request id is also on a server error: a defect a stranger can trigger."""
    probe_ids: dict[str, Any] = {}
    for request in requests:
        if probe_class(request.path, request.query) is not None and request.cid:
            probe_ids.setdefault(request.cid, request)
    found: list[Finding] = []
    for exc_type, view, cid, count in collect.errors_for(list(probe_ids)):
        request = probe_ids.get(cid)
        if request is None:
            continue
        found.append(
            Finding(
                key=f'probe_triggered_error:{clean(exc_type, 60)}:{clean(view, 60)}',
                kind='probe_triggered_error',
                severity=Severity.HIGH,
                subject=request.net,
                title='A probe made the server raise an exception',
                summary=(
                    f'{count} request(s) for a probe path ended in an unhandled {exc_type}'
                    + (f' in {view}' if view else '')
                    + '. An error a stranger can trigger on purpose is a defect to fix first.'
                ),
                count=count,
                first_seen=request.at,
                last_seen=request.at,
                evidence=[cid],
                samples=[clean(request.path)],
                tighten=[
                    Action(
                        'Open the error', 'logs', 'Application errors: find this correlation id.'
                    )
                ],
            )
        )
    return found


def _store_findings(found: list[Finding], now: datetime) -> list[ThreatFinding]:
    rows: list[ThreatFinding] = []
    for finding in found:
        row, created = ThreatFinding.objects.get_or_create(
            key=finding.key,
            defaults={
                'kind': finding.kind,
                'severity': int(finding.severity),
                'subject': finding.subject[:190],
                'title': finding.title[:200],
                'summary': finding.summary,
                'count': finding.count,
                'first_seen': finding.first_seen,
                'last_seen': finding.last_seen,
                'evidence': finding.evidence,
                'samples': finding.samples,
                'tighten': _actions(finding.tighten),
            },
        )
        if not created:
            row.severity = (
                max(row.severity, int(finding.severity))
                if row.status == 'open'
                else int(finding.severity)
            )
            row.summary = finding.summary
            row.count = finding.count
            row.last_seen = max(row.last_seen, finding.last_seen)
            row.evidence = finding.evidence
            row.samples = finding.samples
            row.tighten = _actions(finding.tighten)
            if row.status == ThreatFinding.RESOLVED:
                row.status = ThreatFinding.OPEN  # it came back
                row.notified_at = None
            row.save()
        rows.append(row)
    ThreatFinding.objects.filter(
        status=ThreatFinding.OPEN, last_seen__lt=now - RESOLVE_AFTER
    ).update(status=ThreatFinding.RESOLVED)
    return rows


def _rule_gist(summary: WindowSummary, findings: list[Finding]) -> str:
    if summary.requests == 0 and not findings:
        return 'No traffic was logged in the last hour.'
    head = (
        f'{summary.requests:,} requests from {summary.clients} networks in the last hour'
        f' (busiest minute: {summary.peak_per_minute}).'
    )
    if not findings:
        return f'{head} Nothing in it needs action.'
    by_sev: dict[str, int] = defaultdict(int)
    for finding in findings:
        by_sev[finding.severity.word] += 1
    counted = ', '.join(f'{n} {word}' for word, n in sorted(by_sev.items(), reverse=True))
    top = findings[0]
    urgent = f'{top.title.lower()}: {top.summary}'
    return f'{head} {len(findings)} finding(s) ({counted}). Most urgent: {urgent}'


def _signature(findings: list[Finding]) -> str:
    return '|'.join(sorted(f'{f.key}:{int(f.severity)}:{f.count // 10}' for f in findings))


def _maybe_summarise(
    digest: ThreatDigest, summary: WindowSummary, findings: list[Finding], now: datetime
) -> bool:
    """Ask the assistant's model for the gist, if one is connected and it is worth the tokens."""
    if not findings:
        return False
    signature = _signature(findings)
    if digest.summary.get('signature') == signature and digest.gist_source == 'assistant':
        return False
    if digest.summarised_at and now - digest.summarised_at < SUMMARY_EVERY:
        return False
    try:
        from backend.apps.core.assistant.services import agent
        from backend.apps.core.assistant.services import config as assistant_config

        settings = assistant_config.current(with_key=True)
        if settings is None:
            return False
        if agent.tokens_today() >= int(settings.daily_tokens * summarize.BUDGET_SHARE):
            return False
        provider = agent._provider(settings)  # noqa: SLF001  (one construction path for models)
    except Exception as exc:
        logger.info('Threat summary needs a connected assistant: %s', exc)
        return False
    written = summarize.write(summary, findings, provider)
    if written is None:
        return False
    digest.gist = written.gist
    digest.gist_source = 'assistant'
    digest.priorities = written.priorities
    digest.correlations = list(dict.fromkeys([*_correlate(findings), *written.correlations]))[:8]
    digest.ignored = written.ignore
    digest.tokens += written.tokens
    digest.summarised_at = now
    digest.summary = {**digest.summary, 'signature': signature}
    return True


def _alert(rows: list[ThreatFinding], now: datetime) -> int:
    """Tell the administrators about a serious finding once a day; record it either way."""
    sent = 0
    for row in rows:
        if row.severity < int(ALERT_AT) or row.status != ThreatFinding.OPEN:
            continue
        if row.notified_at and now - row.notified_at < ALERT_EVERY:
            continue
        row.notified_at = now
        row.save(update_fields=['notified_at'])
        AuditService.record(
            action='threat_detected',
            user='system',
            detail=f'{row.kind} {row.subject}: {row.title}',
            severity='warning',
        )
        if os.environ.get('THREAT_ALERTS', '1').lower() in ('0', 'false', 'no'):
            continue
        from backend.apps.mail.services import containment

        recipients = containment._recipients_of_alerts(())  # noqa: SLF001
        if not recipients:
            continue
        steps = (
            '\n'.join(f'  - {a["label"]}: {a["detail"]}' for a in row.tighten) or '  - Review it.'
        )
        try:
            send_mail(
                f'Security finding ({_word(row.severity)}): {row.title}',
                f'{row.summary}\n\nSubject: {row.subject}\nWhere to tighten:\n{steps}\n\n'
                'Details are on the Threats page of the console.',
                None,
                recipients,
                fail_silently=False,
            )
            sent += 1
        except Exception:
            logger.exception('Could not email the threat alert')
    return sent


def _word(severity: int) -> str:
    return Severity(severity).word


def _delivery_findings(summary: WindowSummary, now: datetime) -> list[Finding]:
    """Delivery problems over the last day: earlier hours from the digests, plus this window."""
    hour = now.replace(minute=0, second=0, microsecond=0)
    rows = list(
        ThreatDigest.objects.filter(hour__gte=now - timedelta(hours=24), hour__lt=hour).values_list(
            'summary', flat=True
        )
    )
    rows.append({'sources': summary.sources})
    return delivery.findings([r or {} for r in rows], now)


def run(now: datetime | None = None, *, summarise: bool = True) -> DigestResult:
    now = now or datetime.now(UTC)
    start = access_log.window_start(now, WINDOW_MINUTES)
    log = access_log.read_window(start)
    auth_all = collect.auth_events(now - timedelta(hours=AUTH_HOURS))
    auth_window = [e for e in auth_all if e.at >= start]
    summary = rules.summarise(log.requests, auth_window, start, now, log.skipped_bytes)
    mail, mail_stats = mail_log.read_window_with_stats(start, now)
    summary.mail_failures = mail_rules.failures(mail)
    summary.sources = rollup.build(log, mail, mail_stats)
    found = rules.analyze(log.requests, auth_all, now)
    found += mail_rules.analyze(mail)
    found += _probe_errors(log.requests)
    found += adaptive.run(log.requests, auth_window, mail, found, summary, now)
    found += rollup.findings(summary.sources, now)
    found += _delivery_findings(summary, now)
    found.sort(key=lambda f: (-int(f.severity), -f.count, f.key))

    with transaction.atomic():
        rows = _store_findings(found, now)
        hour = now.replace(minute=0, second=0, microsecond=0)
        digest, _ = ThreatDigest.objects.get_or_create(hour=hour)
        digest.summary = {**_as_dict(summary), 'signature': digest.summary.get('signature', '')}
        digest.findings_count = len(found)
        digest.top_severity = int(found[0].severity) if found else 0
        summarised = False
        if summarise and enabled():
            summarised = _maybe_summarise(digest, summary, found, now)
        if not summarised and digest.gist_source != 'assistant':
            digest.gist = _rule_gist(summary, found)
            digest.correlations = _correlate(found)
            digest.priorities = [
                {'key': f.key, 'why': f.summary} for f in found[:5] if f.severity >= Severity.MEDIUM
            ]
        digest.save()
    alerted = _alert(rows, now)
    return DigestResult(summary, found, digest, log.available, alerted, summarised)


def compact(now: datetime | None = None) -> dict[str, int]:
    """Discard what the digests have already summarised. The audit trail is never touched."""
    now = now or datetime.now(UTC)
    noise, _ = ErrorEvent.objects.filter(
        severity__in=['DEBUG', 'INFO', 'WARNING'], created_at__lt=now - NOISE_AGE
    ).delete()
    # Refusals recorded before they stopped being errors (a rollback, an old release).
    refused, _ = ErrorEvent.objects.filter(
        exc_type__in=('DisallowedHost', 'Resolver404', 'Http404')
    ).delete()
    noise += refused
    quiet, _ = ThreatDigest.objects.filter(
        findings_count=0, hour__lt=now - KEEP_QUIET_DIGESTS
    ).delete()
    old, _ = ThreatDigest.objects.filter(hour__lt=now - KEEP_DIGESTS).delete()
    findings, _ = ThreatFinding.objects.filter(
        status=ThreatFinding.RESOLVED, last_seen__lt=now - KEEP_RESOLVED
    ).delete()
    places = adaptive.forget(now)
    return {
        'noise_events': noise,
        'quiet_digests': quiet + old,
        'findings': findings,
        'places': places,
    }
