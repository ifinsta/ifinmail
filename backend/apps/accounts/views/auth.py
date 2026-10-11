"""Authentication views: login, logout, staff check."""

import functools
import logging
import os

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import ensure_csrf_cookie

from backend.apps.accounts.services.setup_state import SetupState
from backend.apps.core.platform.services.audit import AuditService

from ._constants import _ALLOWED_HOST_NAMES
from .registration import _send_verification_email

logger = logging.getLogger('backend')


_RATE_LIMIT_MAX = 10  # max login attempts
_RATE_LIMIT_WINDOW = 300  # per 5 minutes


def _is_staff(user: object) -> bool:
    """Check staff status with database revalidation."""
    if not user.is_authenticated:
        return False
    try:
        user.refresh_from_db(fields=['is_staff', 'is_superuser', 'is_active'])
    except ObjectDoesNotExist:
        logger.warning('User object disappeared during staff check')
        return False
    if not user.is_active:
        return False
    return user.is_staff or user.is_superuser


def require_perm(code: str):
    """Staff gate plus one neutral permission code.

    Outsiders (anonymous, inactive, non-staff) are sent to sign-in exactly
    like the old staff-only gates, so existing redirect expectations hold.
    Authenticated staff lacking the code get a 403 — a state that could not
    exist before roles.
    """

    def decorator(view_func):
        @functools.wraps(view_func)
        def wrapper(request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
            if not _is_staff(request.user):
                from django.contrib.auth.views import redirect_to_login

                return redirect_to_login(request.get_full_path())
            from backend.apps.accounts.services.roles import RoleService

            if not RoleService.has_perm(request.user, code):
                from django.core.exceptions import PermissionDenied

                raise PermissionDenied(f'This login cannot: {code}')
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


def _get_client_ip(request: HttpRequest) -> str:
    """Extract client IP from request headers."""
    x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if x_forwarded:
        return x_forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


@ensure_csrf_cookie
def login_view(request: HttpRequest) -> HttpResponse:
    """Admin login view."""
    error = None

    if request.method == 'GET' and request.GET.get('timeout_minutes', '').isdigit():
        minutes = max(1, min(1440, int(request.GET['timeout_minutes'])))
        error = f'You were signed out after {minutes} minutes of inactivity.'

    # Rate-limit check (backup for Axes)
    client_ip = _get_client_ip(request)
    rate_key = f'login_rate:{client_ip}'
    attempts = cache.get(rate_key, 0)
    if attempts >= _RATE_LIMIT_MAX:
        logger.warning('Rate limit exceeded for IP %s', client_ip)
        error = 'Too many login attempts. Try again later.'
        return render(request, 'admin/login.html', {'error': error})

    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')

        # Handle verification email resend from the inactive-account banner
        if request.POST.get('resend') == '1' and email:
            user_model = get_user_model()
            exists = user_model.objects.filter(email=email, is_active=False).exists()
            if exists:
                _send_verification_email(request, email)
            return render(
                request,
                'admin/login.html',
                {
                    'resent': True,
                    'resent_email': email,
                    'inactive': True,
                    'inactive_email': email,
                    'error': "This account hasn't been verified yet.",
                },
            )

        # Check for Axes lockout before attempting auth
        try:
            from axes.conf import settings as axes_settings
            from axes.helpers import get_lockout_message, is_already_locked

            if callable(axes_settings.AXES_LOCKOUT_CALLABLE):
                credentials = {'username': email, 'ip_address': request.META.get('REMOTE_ADDR', '')}
                if axes_settings.AXES_LOCKOUT_CALLABLE(request, credentials):
                    error = get_lockout_message(request) or 'Account locked. Try again later.'
                    AuditService.record(
                        'login_blocked',
                        user=email,
                        detail='Account locked by Axes',
                        severity='warn',
                    )
                    return render(request, 'admin/login.html', {'error': error})
            elif is_already_locked(request):
                error = get_lockout_message(request) or 'Account locked. Try again later.'
                AuditService.record(
                    'login_blocked',
                    user=email,
                    detail='Account locked by Axes',
                    severity='warn',
                )
                return render(request, 'admin/login.html', {'error': error})
        except ImportError:
            pass

        user = authenticate(request, username=email, password=password)
        if user is not None:
            # Clear rate-limit on success
            cache.delete(rate_key)

            if not (user.is_staff or user.is_superuser):
                # Correct credentials for an ordinary mailbox: there is no webmail or console
                # for them, so say where to use the mailbox instead of bouncing back silently.
                AuditService.record(
                    'login_mailbox_only',
                    user=user.email,
                    detail=f'IP: {client_ip}',
                    severity='info',
                )
                return render(
                    request,
                    'admin/login.html',
                    {
                        'mailbox_notice': True,
                        'mailbox_address': user.email,
                        'mail_host': os.environ.get('MAIL_HOSTNAME', ''),
                    },
                )

            request.session.cycle_key()
            from backend.apps.accounts.services.mfa import TOTPService

            if TOTPService.has_verified_device(user):
                # Password done, code still required: hold the user id in the
                # (freshly cycled) session and verify before login() is called.
                request.session['mfa_pending_user_id'] = str(user.pk)
                return redirect('accounts:mfa_verify')
            # No device yet: log in, but flag the session so the enforcement
            # middleware routes every console page to enrollment. A login that
            # turned its own second factor off is not forced back.
            if user.mfa_required:
                request.session['mfa_setup_required'] = True
            login(request, user)

            AuditService.record(
                'login_success',
                user=user.email,
                detail=f'IP: {client_ip}',
                severity='info',
            )

            next_url = request.GET.get('next', '')
            if next_url and url_has_allowed_host_and_scheme(
                next_url,
                allowed_hosts=_ALLOWED_HOST_NAMES or None,
            ):
                return redirect(next_url)
            if (user.is_staff or user.is_superuser) and not SetupState.is_complete():
                return redirect('accounts:setup_wizard')
            if (user.is_staff or user.is_superuser) and user.mfa_required:
                return redirect('accounts:mfa_setup')
            return redirect('accounts:dashboard')

        # Increment rate-limit on failure
        cache.set(rate_key, attempts + 1, _RATE_LIMIT_WINDOW)

        # Check if user exists but is inactive (unverified)
        user_model = get_user_model()
        try:
            existing = user_model.objects.get(email=email)
            if not existing.is_active:
                AuditService.record(
                    'login_inactive',
                    user=email,
                    detail=f'IP: {client_ip}',
                    severity='info',
                )
                return render(
                    request,
                    'admin/login.html',
                    {
                        'error': "This account hasn't been verified yet.",
                        'inactive': True,
                        'inactive_email': email,
                    },
                )
        except user_model.DoesNotExist:
            pass

        AuditService.record(
            'login_failed',
            user=email,
            detail=f'IP: {client_ip}',
            severity='warn',
        )
        error = 'Invalid email or password.'
    from backend.apps.accounts.services.initial_admin import InitialAdminService

    # First sign-in after install: say which address to use and where the password is kept.
    first_signin_email = InitialAdminService.pending_signin_email()
    return render(
        request,
        'admin/login.html',
        {
            'error': error,
            'first_signin_email': first_signin_email,
            'install_dir': os.environ.get('IFINMAIL_INSTALL_DIR', '') if first_signin_email else '',
        },
    )


def logout_view(request: HttpRequest) -> HttpResponse:
    """Admin logout view — fully flush session to prevent reuse across tabs."""
    AuditService.record(
        'logout',
        user=getattr(request.user, 'email', 'unknown'),
        detail='User logged out',
        severity='info',
    )
    request.session.flush()
    logout(request)
    return redirect('accounts:login')
