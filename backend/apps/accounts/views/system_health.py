"""System health page: one verdict, what to do next, and the checks grouped by area."""

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from backend.apps.accounts.services.system_health import HealthReport, SystemHealth

from ..types.permissions import PermissionCode
from .auth import require_perm

_CONSOLE = require_perm(PermissionCode.CONSOLE_ACCESS)

_ASK_REVIEW = (
    'Review my System health report. Tell me in plain language what matters most and what to '
    'fix first.'
)


def _verdict(report: HealthReport) -> dict:
    """The page's one-sentence answer: how things stand and the first thing to do."""
    attention = report.attention
    first = attention[0] if attention else None
    if report.errors:
        tone = 'danger'
    elif report.warnings:
        tone = 'warning'
    elif report.waiting:
        tone = 'info'
    else:
        tone = 'ok'
    return {
        'tone': tone,
        'errors': report.errors,
        'warnings': report.warnings,
        'waiting': len(report.waiting),
        'first': first,
        'first_group_slug': slugify(first.group) if first else '',
    }


def _groups(report: HealthReport) -> list[dict]:
    """Check groups in report order, with how many of each need attention."""
    out: dict[str, dict] = {}
    for check in report.checks:
        slug = slugify(check.group)
        item = out.setdefault(
            slug, {'name': check.group, 'slug': slug, 'total': 0, 'attention': 0, 'worst': 'ok'}
        )
        item['total'] += 1
        if check.state in ('error', 'warning', 'unknown'):
            item['attention'] += 1
            if check.state == 'error' or item['worst'] == 'ok':
                item['worst'] = 'danger' if check.state == 'error' else 'warning'
    return list(out.values())


@login_required
@_CONSOLE
def system_health(request: HttpRequest) -> HttpResponse:
    from backend.apps.core.platform.services.updates import UpdateService

    full = SystemHealth.report()
    groups = _groups(full)
    wanted = request.GET.get('group', '').strip().lower()
    chosen = next((g for g in groups if g['slug'] == wanted), None)
    shown = (
        HealthReport(
            checked_at=full.checked_at,
            checks=[c for c in full.checks if slugify(c.group) == chosen['slug']],
        )
        if chosen
        else full
    )
    return render(
        request,
        'admin/system_health.html',
        {
            'report': shown,
            'full_report': full,
            'verdict': _verdict(full),
            'groups': groups,
            'group': chosen,
            'ask_review': _ASK_REVIEW,
            'just_checked': (timezone.now() - full.checked_at).total_seconds() < 60,
            'updates': UpdateService.status(),
            'active_section': 'health',
            'header_search_placeholder': 'Search mail server logs...',
        },
    )


@login_required
@_CONSOLE
@require_POST
def system_health_recheck(request: HttpRequest) -> HttpResponse:
    SystemHealth.report(refresh=True)
    return redirect('accounts:system_health')


@login_required
@_CONSOLE
@require_POST
def system_health_updates(request: HttpRequest) -> HttpResponse:
    """Switch the six-hourly GitHub release check on or off."""
    from backend.apps.core.platform.services.audit import AuditService
    from backend.apps.core.platform.services.updates import UpdateService

    enabled = request.POST.get('enabled') == '1'
    UpdateService.set_enabled(enabled)
    AuditService.record(
        action='update_check_toggled', user=request.user.email, detail='on' if enabled else 'off'
    )
    SystemHealth.report(refresh=True)
    return redirect('accounts:system_health')
