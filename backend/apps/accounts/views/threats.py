"""Threats: what is probing or attacking this server, and where to tighten.

Reads what the threat digest (``core.telemetry.threats``) keeps: an hourly slim summary and the
findings that carry a threat. Nothing on this page is raw log data, and the only actions are
links to the console pages that already hold each control.
"""

from __future__ import annotations

import ipaddress
from datetime import timedelta
from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from backend.apps.core.platform.services.audit import AuditService
from backend.apps.core.platform.services.entrypoints import EntryPointService, NetworkError
from backend.apps.core.telemetry.models import ThreatDigest, ThreatFinding
from backend.apps.core.telemetry.threats import access_log, adaptive, digest, geo, rules
from backend.apps.core.telemetry.threats.types import Severity

from ..forms.server import ThreatBlockForm
from ..services.roles import RoleService
from ..services.stepup import StepUpService
from ..types.permissions import PermissionCode
from .auth import require_perm
from .server import blocklist_row, protected_addresses

_VIEW = require_perm(PermissionCode.AUDIT_VIEW)
_MANAGE = require_perm(PermissionCode.SYSTEM_MANAGE)
_FIREWALL = require_perm(PermissionCode.SECURITY_MANAGE)

_BLOCK_FOR = {
    '1h': timedelta(hours=1),
    '24h': timedelta(hours=24),
    '7d': timedelta(days=7),
    'forever': None,
}

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


_CAMPAIGN = 'campaign'
_SAMPLES_LABEL = {'campaign': 'Networks', 'new_place': 'Place'}


def _campaign_targets(row: ThreatFinding) -> list[str]:
    """The networks of a campaign finding that a person may block from here."""
    found = []
    for sample in row.samples or []:
        try:
            net = str(ipaddress.ip_network(str(sample), strict=False))
        except ValueError:
            continue
        if not rules.is_internal(net):
            found.append(net)
    return found


def _present(
    row: ThreatFinding, blocked: dict[str, dict[str, Any]], place: str = ''
) -> dict[str, Any]:
    severity = Severity(min(max(row.severity, 0), 4))
    is_network = row.kind in rules.NETWORK_KINDS and bool(row.subject)
    held = blocked.get(row.subject) if is_network else None
    campaign = (
        [n for n in _campaign_targets(row) if n not in blocked] if row.kind == _CAMPAIGN else []
    )
    return {
        'place': place,
        'blocked': held is not None,
        'blocked_until': held.get('until') if held else None,
        'blockable': (is_network and held is None and not rules.is_internal(row.subject))
        or bool(campaign),
        'campaign_count': len(campaign),
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
        'samples_label': (
            'Accounts tried'
            if row.kind.startswith('mail_')
            else _SAMPLES_LABEL.get(row.kind, 'Requested')
        ),
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
    blocked: dict[str, dict[str, Any]] = {
        str(r['cidr']): r for r in map(blocklist_row, EntryPointService.active_blocklist(now))
    }
    reader = geo.reader()
    try:
        findings = [
            _present(
                r,
                blocked,
                reader.lookup_net(r.subject).text()
                if reader is not None and r.kind in rules.NETWORK_KINDS
                else '',
            )
            | {'why': priorities.get(r.key, '')}
            for r in open_rows
        ]
    finally:
        if reader is not None:
            reader.close()
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
            'countries': sorted((summary.get('countries') or {}).items(), key=lambda kv: -kv[1]),
            'providers': summary.get('providers') or [],
            'adaptive': adaptive.status(),
            'can_manage': RoleService.has_perm(request.user, PermissionCode.SYSTEM_MANAGE),
            'can_block': RoleService.has_perm(request.user, PermissionCode.SECURITY_MANAGE),
        },
    )


def _finding(pk: str) -> ThreatFinding | None:
    try:
        return ThreatFinding.objects.filter(pk=pk).first()
    except (ValidationError, ValueError):
        return None


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
    row = _finding(request.POST.get('finding', ''))
    if row is None:
        messages.error(request, 'That finding is already gone.')
        return redirect('accounts:threats')
    row.status = ThreatFinding.OPEN if request.POST.get('undo') else ThreatFinding.ACKNOWLEDGED
    row.save(update_fields=['status', 'updated_at'])
    AuditService.record(
        action='threat_finding_acknowledged', user=request.user.email, detail=row.key
    )
    return redirect('accounts:threats')


@login_required
@_FIREWALL
@require_POST
def threats_block(request: HttpRequest) -> HttpResponse:
    """Block the network (or the networks of a campaign) a finding is about: password again,
    never your own side, and each block lifts itself."""
    back = redirect('accounts:threats')
    form = ThreatBlockForm(request.POST)
    row = _finding(request.POST.get('finding', '')) if form.is_valid() else None
    if row is None:
        messages.error(request, 'That finding is already gone.')
        return back
    if row.kind == _CAMPAIGN:
        targets = _campaign_targets(row)
    elif row.kind in rules.NETWORK_KINDS and row.subject:
        targets = [row.subject]
    else:
        targets = []
    if not targets:
        messages.error(
            request, 'This finding is not about a network, so there is nothing to block.'
        )
        return back
    if len(targets) == 1 and rules.is_internal(targets[0]):
        messages.error(
            request, f'{targets[0]} is on this server’s own side, so it is never blocked here.'
        )
        return back
    problem = StepUpService.confirm(request)
    if problem:
        messages.error(request, problem)
        return back
    lifetime = _BLOCK_FOR[form.cleaned_data['duration']]
    expires_at = timezone.now() + lifetime if lifetime else None
    until = f'until {expires_at:%Y-%m-%d %H:%M} UTC' if expires_at else 'until removed'
    done: list[str] = []
    refused: list[str] = []
    protect = protected_addresses(request)
    for net in targets:
        try:
            text = EntryPointService.block(
                net, f'Threats: {row.title}', protect=protect, expires_at=expires_at
            )
        except NetworkError as exc:
            refused.append(str(exc))
            continue
        done.append(text)
        AuditService.record(
            action='network_block',
            user=request.user.email,
            detail=f'{text} {until} (finding {row.key})',
        )
    if not done:
        messages.error(request, refused[0])
        return back
    row.status = ThreatFinding.ACKNOWLEDGED
    row.save(update_fields=['status', 'updated_at'])
    note = f' ({len(refused)} left alone: already blocked or yours)' if refused else ''
    verb = 'is' if len(done) == 1 else 'are'
    messages.success(request, f'{", ".join(done)} {verb} blocked {until}{note}.')
    return back
