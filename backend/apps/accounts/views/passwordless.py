"""Passkeys-only console sign-in: switching it, and the recovery code way back in.

Views -> services/passwordless.py. Switching needs the person's password again (a stolen session
must not be able to lock them out of their own account, or change how they get in); signing in
with a recovery code is the one anonymous endpoint and is rate limited like the password form.
"""

from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from backend.apps.core.platform.services.audit import AuditService

from ..models import MailUser
from ..services.passwordless import PasswordlessError, PasswordlessService
from ..services.stepup import StepUpService
from ..types.permissions import PermissionCode
from .auth import _get_client_ip, require_perm
from .mfa import _mark_verified

logger = logging.getLogger(__name__)
_CONSOLE = require_perm(PermissionCode.CONSOLE_ACCESS)
_MANAGE = require_perm(PermissionCode.MAIL_MANAGE)
_MODEL_BACKEND = 'django.contrib.auth.backends.ModelBackend'
_ATTEMPTS = 8
_WINDOW = 900
# What an unknown address and a wrong code both cost: one hash check, so timing says nothing.
_DUMMY_HASH = 'pbkdf2_sha256$1000000$ifinmail$' + 'A' * 43 + '='


def _render_page(request: HttpRequest, *, new_codes: list[str] | None = None) -> HttpResponse:
    """The Passkeys page, rendered in place (recovery codes are shown once and never stored)."""
    from .passkeys import passkeys_context

    context = passkeys_context(request)
    context['new_codes'] = new_codes or []
    return render(request, 'admin/passkeys.html', context)


@login_required
@_CONSOLE
@require_POST
def passkeys_only_enable(request: HttpRequest) -> HttpResponse:
    problem = StepUpService.confirm(request)
    if problem:
        messages.error(request, problem)
        return redirect('accounts:passkeys')
    if request.POST.get('understand') != 'on':
        messages.error(request, 'Tick the box to confirm you have read what this changes.')
        return redirect('accounts:passkeys')
    try:
        codes = PasswordlessService.enable(request.user)
    except PasswordlessError as exc:
        messages.error(request, str(exc))
        return redirect('accounts:passkeys')
    AuditService.record(
        action='passkeys_only_enabled',
        user=request.user.email,
        detail='console password sign-in switched off',
        severity='warning',
    )
    messages.success(request, 'Passkeys-only sign-in is on. Save your recovery codes below.')
    return _render_page(request, new_codes=codes)


@login_required
@_CONSOLE
@require_POST
def passkeys_only_disable(request: HttpRequest) -> HttpResponse:
    problem = StepUpService.confirm(request)
    if problem:
        messages.error(request, problem)
        return redirect('accounts:passkeys')
    if PasswordlessService.disable(request.user):
        AuditService.record(
            action='passkeys_only_disabled',
            user=request.user.email,
            detail='console password sign-in allowed again',
            severity='warning',
        )
        messages.success(request, 'Password sign-in is allowed again. Recovery codes were removed.')
    return redirect('accounts:passkeys')


@login_required
@_CONSOLE
@require_POST
def passkeys_only_new_codes(request: HttpRequest) -> HttpResponse:
    problem = StepUpService.confirm(request)
    if problem:
        messages.error(request, problem)
        return redirect('accounts:passkeys')
    try:
        codes = PasswordlessService.new_codes(request.user)
    except PasswordlessError as exc:
        messages.error(request, str(exc))
        return redirect('accounts:passkeys')
    AuditService.record(
        action='passkeys_only_codes_renewed', user=request.user.email, detail='', severity='warning'
    )
    messages.success(request, 'New recovery codes. The old ones no longer work.')
    return _render_page(request, new_codes=codes)


@login_required
@_MANAGE
@require_POST
def mailbox_allow_password_login(request: HttpRequest, mailbox_id: object) -> HttpResponse:
    """Administrator recovery: let this login use its password for the console again."""
    from backend.apps.mail.models import Mailbox
    from backend.apps.mail.services import MailboxService

    mailbox = Mailbox.objects.select_related('domain').filter(id=mailbox_id).first()
    if mailbox is None:
        from django.http import Http404

        raise Http404('mailbox not found')
    address = MailboxService.address_for(mailbox)
    user = MailUser.objects.filter(email=address).first()
    if user is not None and PasswordlessService.disable(user):
        AuditService.record(
            action='passkeys_only_reset',
            user=request.user.email,
            detail=address,
            severity='warning',
        )
        messages.success(request, f'{address} can sign in with its password again.')
    else:
        messages.info(request, f'{address} was not using passkeys-only sign-in.')
    return redirect('accounts:mailbox_profile', mailbox_id=mailbox_id)


# -- the way back in -----------------------------------------------------------------------------


def _limited(key: str) -> bool:
    return cache.get(key, 0) >= _ATTEMPTS


def _bump(key: str) -> None:
    cache.set(key, cache.get(key, 0) + 1, _WINDOW)


@require_http_methods(['GET', 'POST'])
def recovery_login(request: HttpRequest) -> HttpResponse:
    """Sign in with a recovery code when every passkey is lost.

    Only a login that has switched password sign-in off has codes, so this is never a way around
    a password. The answer for an unknown address, a wrong code and a login that has no codes is
    the same sentence.
    """
    if request.method == 'GET':
        return render(request, 'admin/recovery_login.html', {})

    from django.contrib.auth.hashers import check_password

    email = request.POST.get('email', '').strip().lower()
    code = request.POST.get('code', '')
    ip = _get_client_ip(request)
    keys = (f'recovery_ip:{ip}', f'recovery_addr:{email}')
    if any(_limited(k) for k in keys):
        return render(
            request,
            'admin/recovery_login.html',
            {'error': 'Too many attempts. Wait a few minutes and try again.', 'email': email},
        )
    user = MailUser.objects.filter(email=email, is_active=True).first()
    eligible = (
        user is not None
        and (user.is_staff or user.is_superuser)
        and PasswordlessService.is_passwordless(user)
    )
    spent = bool(eligible and PasswordlessService.consume_code(user, code))  # type: ignore[arg-type]
    if not eligible:
        check_password('x', _DUMMY_HASH)  # same cost as a real check
    if not spent:
        for key in keys:
            _bump(key)
        AuditService.record(
            action='recovery_login_failed',
            user=email or 'unknown',
            detail=f'IP: {ip}',
            severity='warning',
        )
        return render(
            request,
            'admin/recovery_login.html',
            {'error': 'That address and code do not match.', 'email': email},
        )
    request.session.cycle_key()
    login(request, user, backend=_MODEL_BACKEND)
    _mark_verified(request, 'recovery')
    for key in keys:
        cache.delete(key)
    AuditService.record(
        action='login_recovery_code',
        user=user.email,  # type: ignore[union-attr]
        detail=f'IP: {ip}; codes left: {PasswordlessService.remaining_codes(user)}',  # type: ignore[arg-type]
        severity='warning',
    )
    messages.warning(
        request,
        'You signed in with a recovery code. Add a new passkey, or allow password sign-in again.',
    )
    target = request.GET.get('next', '')
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        return redirect(target)
    return redirect('accounts:passkeys')
