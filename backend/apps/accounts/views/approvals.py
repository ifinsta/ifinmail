"""Settings → Approvals: messages API keys sent that wait for a person (Human approval plugin)."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from ..types.permissions import PermissionCode
from .auth import require_perm

_MANAGE = require_perm(PermissionCode.MAIL_MANAGE)


@login_required
@_MANAGE
@require_GET
def approvals_page(request: HttpRequest, pending_id: str | None = None) -> HttpResponse:
    from backend.apps.mail.services import approvals

    rows = approvals.listing(key_prefix=None)
    waiting = [r for r in rows if r.status == 'pending']
    decided = [r for r in rows if r.status != 'pending'][:50]
    selected = approvals.get(pending_id) if pending_id else (waiting[0] if waiting else None)
    return render(
        request,
        'admin/settings_approvals.html',
        {
            'active_section': 'approvals',
            'show_settings_icon': True,
            'waiting': waiting,
            'decided': decided,
            'selected': selected,
            'policy': approvals.settings(),
        },
    )


@login_required
@_MANAGE
@require_POST
def approvals_decide(request: HttpRequest) -> HttpResponse:
    from backend.apps.mail.services import approvals

    pending_id = request.POST.get('pending', '')
    note = request.POST.get('note', '')
    actor = getattr(request.user, 'email', '') or 'console'
    try:
        if request.POST.get('decision') == 'approve':
            row = approvals.approve(pending_id, actor=actor, note=note)
        else:
            row = approvals.reject(pending_id, actor=actor, note=note)
    except approvals.ApprovalError as exc:
        messages.error(request, str(exc))
        return redirect('accounts:approvals')
    if row.status == 'sent':
        messages.success(request, f'Approved and sent: {row.subject[:80]}')
    elif row.status == 'failed':
        messages.error(request, f'Approved, but it could not be sent: {row.note}')
    else:
        messages.success(request, f'Rejected: {row.subject[:80]}')
    return redirect('accounts:approvals')
