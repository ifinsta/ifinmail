"""Passkeys: register one, sign in with one (passwordless), or use one as the second step.

The ceremonies are JSON endpoints driven by ``ifinmail-passkeys.js``; the page that lists and
removes passkeys is ordinary HTML. Every state change is audited, adding or removing one needs the
person's password again (a stolen session must not be able to plant its own passkey), and sign-in
endpoints are rate limited per address.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from backend.apps.core.platform.services.audit import AuditService

from ..models import Passkey
from ..services import passkeys
from ..services.mfa import TOTPService
from ..services.stepup import StepUpService
from ..services.webauthn import WebAuthnError
from ..types.permissions import PermissionCode
from .auth import _get_client_ip, require_perm
from .mfa import _mark_verified

logger = logging.getLogger('backend')

_CONSOLE = require_perm(PermissionCode.CONSOLE_ACCESS)
_MODEL_BACKEND = 'django.contrib.auth.backends.ModelBackend'
_LIMIT = 20  # passkey sign-in attempts per address
_WINDOW = 600


def _actor(request: HttpRequest) -> str | None:
    return request.user.email if request.user.is_authenticated else None


def _error(message: str, status: int = 400) -> JsonResponse:
    return JsonResponse({'ok': False, 'error': message}, status=status)


def _limited(request: HttpRequest) -> bool:
    key = f'passkey_attempts:{_get_client_ip(request)}'
    try:
        attempts = cache.get(key, 0)
        if attempts >= _LIMIT:
            return True
        cache.set(key, attempts + 1, _WINDOW)
    except Exception:  # a cache outage must not lock everyone out
        return False
    return False


# -- the page ------------------------------------------------------------------------------------


@login_required
@_CONSOLE
@require_GET
def passkeys_page(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        'admin/passkeys.html',
        {
            'active_section': 'passkeys',
            'show_settings_icon': True,
            'passkeys': passkeys.for_user(request.user),
            'supported': passkeys.available(request),
            'max_passkeys': passkeys.MAX_PER_USER,
            'has_totp': TOTPService.has_verified_device(request.user),
            'enforced': TOTPService.enforced(),
        },
    )


# -- registering ---------------------------------------------------------------------------------


@login_required
@_CONSOLE
@require_POST
def passkey_register_options(request: HttpRequest) -> JsonResponse:
    problem = StepUpService.confirm(request)
    if problem:
        return _error(problem, 403)
    try:
        options = passkeys.registration_options(request, request.user, request.POST.get('name', ''))
    except WebAuthnError as exc:
        return _error(str(exc))
    return JsonResponse({'ok': True, 'options': options})


@login_required
@_CONSOLE
@require_POST
def passkey_register_verify(request: HttpRequest) -> JsonResponse:
    try:
        row = passkeys.finish_registration(request, request.user, passkeys.parse_json(request))
    except WebAuthnError as exc:
        AuditService.record(
            action='passkey_register_failed',
            user=_actor(request),
            detail=str(exc)[:120],
            severity='warning',
        )
        return _error(str(exc))
    AuditService.record(
        action='passkey_registered',
        user=_actor(request),
        detail=f'{row.name} ({"synced" if row.backup_eligible else "device-bound"})',
    )
    return JsonResponse({'ok': True, 'name': row.name, 'id': str(row.pk)})


@login_required
@_CONSOLE
@require_POST
def passkey_remove(request: HttpRequest) -> HttpResponse:
    problem = StepUpService.confirm(request)
    if problem:
        messages.error(request, problem)
        return redirect('accounts:passkeys')
    try:
        target = uuid.UUID(request.POST.get('id', ''))
    except ValueError:
        messages.error(request, 'That passkey could not be found.')
        return redirect('accounts:passkeys')
    row = Passkey.objects.filter(pk=target, user=request.user).first()
    if row is None:
        messages.error(request, 'That passkey could not be found.')
        return redirect('accounts:passkeys')
    name = row.name
    row.delete()
    AuditService.record(
        action='passkey_removed', user=_actor(request), detail=name, severity='warning'
    )
    messages.success(request, f'“{name}” was removed.')
    return redirect('accounts:passkeys')


# -- signing in (no password) --------------------------------------------------------------------


@require_POST
def passkey_login_options(request: HttpRequest) -> JsonResponse:
    if _limited(request):
        return _error('Too many attempts. Wait a few minutes and try again.', 429)
    try:
        return JsonResponse({'ok': True, 'options': passkeys.authentication_options(request)})
    except WebAuthnError as exc:
        return _error(str(exc))


@require_POST
def passkey_login_verify(request: HttpRequest) -> JsonResponse:
    if _limited(request):
        return _error('Too many attempts. Wait a few minutes and try again.', 429)
    try:
        payload = passkeys.parse_json(request)
        row = passkeys.finish_authentication(request, payload)
    except WebAuthnError as exc:
        AuditService.record(
            action='passkey_login_failed',
            user='unknown',
            detail=f'IP: {_get_client_ip(request)}',
            severity='warning',
        )
        return _error(str(exc), 401)
    user = row.user
    if not (user.is_staff or user.is_superuser):
        # An ordinary mailbox has no console: the same answer a wrong passkey gets.
        return _error('That passkey could not be used. Try again or sign in another way.', 401)
    request.session.cycle_key()
    login(request, user, backend=_MODEL_BACKEND)
    _mark_verified(request, 'passkey')
    AuditService.record(
        action='login_success',
        user=user.email,
        detail=f'method=passkey ({row.name}) IP: {_get_client_ip(request)}',
    )
    return JsonResponse({'ok': True, 'next': _destination(request, payload, user)})


def _destination(request: HttpRequest, payload: dict[str, Any], user: Any) -> str:
    from django.urls import reverse

    from ..services.setup_state import SetupState

    requested = str(payload.get('next') or '')
    if requested and url_has_allowed_host_and_scheme(
        requested, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return requested
    if not SetupState.is_complete():
        return reverse('accounts:setup_wizard')
    return reverse('accounts:dashboard')
