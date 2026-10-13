"""Settings → File storage: where the console's files live, a test, and moving media over."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.management import call_command
from django.core.management.base import CommandError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from backend.apps.core.platform.services.audit import AuditService
from backend.apps.core.storage import config, health

from ..types.permissions import PermissionCode
from .auth import require_perm

_MANAGE = require_perm(PermissionCode.SYSTEM_MANAGE)


@login_required
@_MANAGE
@require_GET
def file_storage(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        'admin/file_storage.html',
        {
            'active_section': 'file-storage',
            'show_settings_icon': True,
            'layout': config.describe(),
            'probe': health.last(),
            'external': config.current() is not None,
            'media_external': config.external('media') is not None,
        },
    )


@login_required
@_MANAGE
@require_POST
def file_storage_probe(request: HttpRequest) -> HttpResponse:
    result = health.run_probe()
    if not result.get('configured', True):
        messages.info(
            request, 'Files are on this server’s disk; there is no external store to test.'
        )
    elif result.get('ok'):
        messages.success(request, result['detail'])
    else:
        messages.error(request, f'The test failed: {result.get("detail", "")}')
    return redirect('accounts:file_storage')


@login_required
@_MANAGE
@require_POST
def file_storage_sync(request: HttpRequest) -> HttpResponse:
    from io import StringIO

    out = StringIO()
    try:
        call_command('storage', 'sync-media', stdout=out)
    except CommandError as exc:
        messages.error(request, str(exc))
        return redirect('accounts:file_storage')
    summary = out.getvalue().strip()
    AuditService.record(action='storage_media_copied', user=request.user.email, detail=summary)
    messages.success(request, summary)
    return redirect('accounts:file_storage')
