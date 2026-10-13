"""Paused senders: mailboxes whose sending containment stopped, and the way to resume them."""

from __future__ import annotations

from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from backend.apps.mail.services import containment

from ..types.permissions import PermissionCode
from .auth import require_perm

_MANAGE = require_perm(PermissionCode.SYSTEM_MANAGE)


def _rows() -> list[dict]:
    rows = []
    for login, entry in sorted(containment.paused().items()):
        try:
            when = datetime.fromisoformat(entry.get('at', ''))
        except ValueError:
            when = None
        usage = entry.get('usage') or {}
        rows.append(
            {
                'login': login,
                'reason': entry.get('reason', ''),
                'when': when,
                'by': entry.get('by', 'system'),
                'messages': usage.get('messages'),
                'recipients': usage.get('recipients'),
                'domains': usage.get('domains'),
            }
        )
    return rows


@login_required
@_MANAGE
@require_GET
def sending(request: HttpRequest) -> HttpResponse:
    limits = containment.thresholds()
    return render(
        request,
        'admin/sending_paused.html',
        {
            'active_section': 'health',
            'rows': _rows(),
            'limits': limits,
            'header_search_placeholder': 'Search mail server logs...',
        },
    )


@login_required
@_MANAGE
@require_POST
def sending_resume(request: HttpRequest) -> HttpResponse:
    login = request.POST.get('login', '').strip().lower()
    if containment.resume(login, actor=request.user.email):
        messages.success(
            request, f'Sending is resumed for {login}. It is counted afresh from now on.'
        )
    else:
        messages.error(request, f'{login or "That mailbox"} is not paused.')
    return redirect('accounts:sending')
