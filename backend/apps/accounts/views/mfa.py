"""Second-factor views: TOTP enrollment (staff) and login verification.

Flow:
* Staff *with* a verified device: password (login view) → code here → session.
  ``login()`` is only called after the code checks out.
* Staff *without* a device: normal login, but the session is flagged and
  ``MFAEnforcementMiddleware`` routes every console page to enrollment until
  one device is verified.
"""

from __future__ import annotations

import uuid

from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from backend.apps.accounts.services.mfa import MFAError, TOTPService
from backend.services.audit import AuditService

from ..types.permissions import PermissionCode
from .auth import _get_client_ip, require_perm

_CONSOLE = require_perm(PermissionCode.CONSOLE_ACCESS)

_VERIFY_LIMIT_MAX = 5  # code attempts
_VERIFY_LIMIT_WINDOW = 300  # per 5 minutes


def _actor(request: HttpRequest) -> str | None:
    return request.user.email if request.user.is_authenticated else None


def _mark_verified(request: HttpRequest, method: str) -> None:
    now = timezone.now().isoformat()
    request.session['mfa_verified_at'] = now
    request.session['mfa_method'] = method
    request.session.pop('mfa_setup_required', None)
    request.session.pop('mfa_pending_user_id', None)


def _qr_data_uri(uri: str) -> str:
    """Render an ``otpauth://`` URI as an inline SVG data-URI QR code.

    The ``qrcode`` dependency is imported lazily and the login-path service stays
    stdlib-only; if the package is unavailable this returns '' and the enrollment
    page falls back to manual key entry.
    """
    if not uri:
        return ''
    try:
        import base64

        import qrcode
        from qrcode.image.svg import SvgPathImage
    except ImportError:
        return ''
    try:
        qr = qrcode.QRCode(border=2)
        qr.add_data(uri)
        qr.make(fit=True)
        svg = qr.make_image(image_factory=SvgPathImage).to_string()
        if isinstance(svg, str):
            svg = svg.encode('utf-8')
        return 'data:image/svg+xml;base64,' + base64.b64encode(svg).decode('ascii')
    except Exception:  # pragma: no cover - defensive: never break enrollment
        return ''


# -- enrollment ---------------------------------------------------------------


@login_required
@_CONSOLE
def mfa_setup(request: HttpRequest) -> HttpResponse:
    """Enroll (or replace) the staff authenticator. Secret shown exactly once."""
    status = TOTPService.status_for(request.user)
    if request.method == 'POST':
        action = request.POST.get('action', 'start')
        if action == 'start':
            uri, secret = TOTPService.start_enrollment(request.user)
            AuditService.record(action='mfa_enrollment_started', user=_actor(request), detail='')
            return render(
                request,
                'admin/mfa_setup.html',
                {
                    'stage': 'confirm',
                    'uri': uri,
                    'secret': secret,
                    'qr': _qr_data_uri(uri),
                    'status': status,
                },
            )
        if action == 'confirm':
            try:
                codes = TOTPService.confirm_enrollment(request.user, request.POST.get('code', ''))
            except MFAError as exc:
                return render(
                    request,
                    'admin/mfa_setup.html',
                    {
                        'stage': 'confirm',
                        'uri': None,
                        'secret': None,
                        'status': status,
                        'error': f'{exc} Start again to get a fresh secret.',
                    },
                )
            AuditService.record(action='mfa_enrolled', user=_actor(request), detail='')
            _mark_verified(request, 'totp')
            return render(
                request,
                'admin/mfa_setup.html',
                {
                    'stage': 'done',
                    'status': TOTPService.status_for(request.user),
                    'recovery_codes': codes,
                },
            )
        if action == 'regenerate':
            if not status['enabled']:
                messages.error(request, 'Enroll an authenticator first.')
                return redirect('accounts:mfa_setup')
            codes = TOTPService.fresh_recovery_codes(request.user)
            AuditService.record(action='mfa_recovery_regenerated', user=_actor(request), detail='')
            return render(
                request,
                'admin/mfa_setup.html',
                {
                    'stage': 'done',
                    'status': TOTPService.status_for(request.user),
                    'recovery_codes': codes,
                },
            )
    return render(request, 'admin/mfa_setup.html', {'stage': 'start', 'status': status})


# -- login verification --------------------------------------------------------


def _verify_limited(request: HttpRequest, user_id: str) -> bool:
    return cache.get(f'mfa_attempts:{user_id}', 0) >= _VERIFY_LIMIT_MAX


def _verify_bump(request: HttpRequest, user_id: str) -> None:
    try:
        attempts = cache.get(f'mfa_attempts:{user_id}', 0)
        cache.set(f'mfa_attempts:{user_id}', attempts + 1, _VERIFY_LIMIT_WINDOW)
    except Exception:
        pass


def mfa_verify(request: HttpRequest) -> HttpResponse:
    """Second step of staff login. Only reachable with a pending session."""
    pending_id = request.session.get('mfa_pending_user_id')
    if not pending_id:
        return redirect('accounts:login')
    user_model = get_user_model()
    user = user_model.objects.filter(pk=pending_id, is_active=True).first()
    if user is None:
        return redirect('accounts:login')
    error = ''
    if request.method == 'POST':
        if _verify_limited(request, str(pending_id)):
            error = 'Too many attempts. Wait a few minutes and try again.'
        else:
            try:
                method = TOTPService.verify_login(user, request.POST.get('code', ''))
            except MFAError as exc:
                _verify_bump(request, str(pending_id))
                AuditService.record(
                    action='mfa_failed', user=user.email, detail='code mismatch', severity='warn'
                )
                error = str(exc)
            else:
                cache.delete(f'mfa_attempts:{str(pending_id)}')
                # Explicit backend: the password step already passed Axes, and
                # the pending user carries no .backend attribute of its own.
                login(request, user, backend='django.contrib.auth.backends.ModelBackend')
                _mark_verified(request, method)
                AuditService.record(
                    action='mfa_verified',
                    user=user.email,
                    detail=f'method={method} IP: {_get_client_ip(request)}',
                )
                from backend.apps.accounts.services.setup_state import SetupState

                if not SetupState.is_complete():
                    return redirect('accounts:setup_wizard')
                return redirect('accounts:dashboard')
    return render(request, 'admin/mfa_verify.html', {'error': error, 'email': user.email})


# -- admin-assisted recovery ----------------------------------------------------


@login_required
@require_perm(PermissionCode.MAIL_MANAGE)
@require_POST
def mailbox_mfa_reset(request: HttpRequest, mailbox_id: uuid.UUID) -> HttpResponse:
    """Remove another profile's devices + codes (e.g. lost authenticator)."""
    from backend.apps.accounts.models import MailUser
    from backend.apps.mail.models import Mailbox
    from backend.apps.mail.services import MailboxService

    mailbox = Mailbox.objects.select_related('domain').filter(id=mailbox_id).first()
    if mailbox is None:
        from django.http import Http404

        raise Http404('mailbox not found')
    address = MailboxService.address_for(mailbox)
    user = MailUser.objects.filter(email=address).first()
    if user is None:
        messages.error(request, f'{address} has no login to reset.')
        return redirect('accounts:mailbox_profile', mailbox_id=mailbox_id)
    if user.pk == request.user.pk:
        messages.error(
            request, 'You cannot reset your own second factor here — enroll a new one instead.'
        )
        return redirect('accounts:mailbox_profile', mailbox_id=mailbox_id)
    TOTPService.reset(user)
    AuditService.record(
        action='mfa_reset', user=_actor(request), detail=address, severity='warning'
    )
    messages.success(
        request, f'Second factor removed for {address}. They must enroll again at next sign-in.'
    )
    return redirect('accounts:mailbox_profile', mailbox_id=mailbox_id)
