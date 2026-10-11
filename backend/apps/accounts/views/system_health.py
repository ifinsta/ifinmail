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
    report = SystemHealth.report()
    return render(
        request,
        'admin/system_health.html',
        {
            'report': report,
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
