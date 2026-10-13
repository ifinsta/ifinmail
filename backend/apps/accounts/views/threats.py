"""Threats: what is probing or attacking this server, and where to tighten.

Reads what the threat digest (``core.telemetry.threats``) keeps: an hourly slim summary and the
findings that carry a threat. Nothing on this page is raw log data, and the only actions are
links to the console pages that already hold each control.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from backend.apps.core.platform.services.audit import AuditService
from backend.apps.core.telemetry.models import ThreatDigest, ThreatFinding
from backend.apps.core.telemetry.threats import access_log, digest
from backend.apps.core.telemetry.threats.types import Severity

from ..services.roles import RoleService
from ..types.permissions import PermissionCode
from .auth import require_perm

_VIEW = require_perm(PermissionCode.AUDIT_VIEW)
_MANAGE = require_perm(PermissionCode.SYSTEM_MANAGE)

# The symbols the digest uses for "where", resolved here so the digest never imports a URL.
_WHERE = {
    'network': ('accounts:network', {}),
    'security': ('accounts:settings_page', {'slug': 'security'}),
    'api_keys': ('accounts:api_keys', {}),
    'users': ('accounts:user_management', {}),
    'logs': ('accounts:logs', {}),
    'health': ('accounts:system_health', {}),
}
_TONE = {
    Severity.CRITICAL: 'danger',
    Severity.HIGH: 'danger',
    Severity.MEDIUM: 'warning',
    Severity.LOW: 'info',
    Severity.INFO: 'info',
}


def _link(where: str) -> str:
    target = _WHERE.get(where)
    return reverse(target[0], kwargs=target[1]) if target else ''


def _verdict(findings: list[ThreatFinding], log_available: bool) -> dict[str, Any]:
    top = max((f.severity for f in findings), default=-1)
    if not log_available and top < 0:
        return {
            'tone': 'info',
            'headline': 'No access log is being read yet.',
            'next': 'It appears after the next update restarts the web server.',
        }
    if top >= int(Severity.CRITICAL):
        return {
            'tone': 'danger',
            'headline': 'Act now: something serious was found.',
            'next': 'Start with the first finding below.',
        }
    if top >= int(Severity.HIGH):
        return {
            'tone': 'danger',
            'headline': 'The server is being actively attacked.',
            'next': 'Tighten the places listed under each finding.',
        }
    if top >= int(Severity.MEDIUM):
        return {
            'tone': 'warning',
            'headline': 'Scanners are probing the server.',
            'next': 'None of it got in. The suggestions below make it quieter.',
        }
    if top >= 0:
        return {
            'tone': 'info',
            'headline': 'Minor background noise.',
            'next': 'Nothing needs doing.',
        }
    return {'tone': 'ok', 'headline': 'Quiet: nothing that needs action.', 'next': ''}


def _present(row: ThreatFinding) -> dict[str, Any]:
    severity = Severity(min(max(row.severity, 0), 4))
    return {
        'id': row.pk,
        'key': row.key,
        'title': row.title,
        'summary': row.summary,
        'subject': row.subject,
        'severity': severity.word,
        'tone': _TONE[severity],
        'count': row.count,
        'first_seen': row.first_seen,
        'last_seen': row.last_seen,
        'status': row.status,
        'evidence': row.evidence,
        'samples': row.samples,
        'tighten': [{**a, 'url': _link(a.get('where', ''))} for a in (row.tighten or [])],
    }


@login_required
@_VIEW
@require_GET
def threats(request: HttpRequest) -> HttpResponse:
    now = timezone.now()
    open_rows = list(
        ThreatFinding.objects.exclude(status=ThreatFinding.RESOLVED).order_by(
            '-severity', '-last_seen'
        )
    )
    latest = ThreatDigest.objects.order_by('-hour').first()
    history = list(
        ThreatDigest.objects.filter(hour__gte=now - timedelta(hours=24)).order_by('-hour')
    )
    summary = (latest.summary if latest else {}) or {}
    priorities = {p.get('key'): p.get('why', '') for p in (latest.priorities if latest else [])}
    findings = [_present(r) | {'why': priorities.get(r.key, '')} for r in open_rows]
    from backend.apps.core.assistant.services import config as assistant_config

    return render(
        request,
        'admin/threats.html',
        {
            'active_section': 'threats',
            'show_settings_icon': True,
            'verdict': _verdict(open_rows, access_log.log_path().exists()),
            'digest': latest,
            'summary': summary,
            'findings': findings,
            'urgent': [f for f in findings if f['severity'] in ('critical', 'high')],
            'history': history,
            'assistant_connected': assistant_config.current() is not None,
            'log_available': access_log.log_path().exists(),
            'can_manage': RoleService.has_perm(request.user, PermissionCode.SYSTEM_MANAGE),
        },
    )


@login_required
@_MANAGE
@require_POST
def threats_run(request: HttpRequest) -> HttpResponse:
    result = digest.run()
    AuditService.record(
        action='threat_digest_run',
        user=request.user.email,
        detail=f'{len(result.findings)} finding(s)',
    )
    messages.success(
        request,
        f'Checked the last hour: {result.summary.requests:,} requests, '
        f'{len(result.findings)} finding(s).',
    )
    return redirect('accounts:threats')


@login_required
@_MANAGE
@require_POST
def threats_ack(request: HttpRequest) -> HttpResponse:
    row = ThreatFinding.objects.filter(pk=request.POST.get('finding', '')).first()
    if row is None:
        messages.error(request, 'That finding is already gone.')
        return redirect('accounts:threats')
    row.status = ThreatFinding.OPEN if request.POST.get('undo') else ThreatFinding.ACKNOWLEDGED
    row.save(update_fields=['status', 'updated_at'])
    AuditService.record(
        action='threat_finding_acknowledged', user=request.user.email, detail=row.key
    )
    return redirect('accounts:threats')
