"""System health: what is wrong, pending or recommended on this server, in one list."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from backend.apps.accounts.services.system_health import SystemHealth

from ..types.permissions import PermissionCode
from .auth import require_perm

_CONSOLE = require_perm(PermissionCode.CONSOLE_ACCESS)


@login_required
@_CONSOLE
def system_health(request: HttpRequest) -> HttpResponse:
    from backend.apps.core.platform.services.updates import UpdateService

    report = SystemHealth.report()
    return render(
        request,
        'admin/system_health.html',
        {
            'report': report,
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
