"""Staff session guards: MFA enforcement + idle timeout.

MFAEnforcementMiddleware routes any authenticated staff session without MFA
proof (``mfa_verified_at``) to enrollment — including sessions established
before MFA shipped. Exempt paths keep enrollment, logout, login, the setup
wizard and non-console endpoints reachable.

SessionIdleTimeoutMiddleware ends sessions idle longer than
``SESSION_IDLE_TIMEOUT`` (default 30 min). Activity timestamps update at most
once a minute to avoid a session write on every request.
"""

from __future__ import annotations

import time

from django.conf import settings
from django.contrib.auth import logout
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils.deprecation import MiddlewareMixin


class MFAEnforcementMiddleware(MiddlewareMixin):
    exempt_prefixes = (
        '/accounts/mfa/',
        '/accounts/setup/',
        '/accounts/logout/',
        '/accounts/login/',
        '/accounts/mailbox-setup/',
        '/accounts/registration/',
        '/accounts/password-reset/',
        '/health',
        '/static/',
        '/admin/',
    )

    def process_view(
        self, request: HttpRequest, view_func: object, view_args: object, view_kwargs: object
    ) -> HttpResponse | None:
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated:
            return None
        if not user.is_active or not (user.is_staff or user.is_superuser):
            return None
        if request.session.get('mfa_verified_at'):
            return None
        if getattr(user, 'mfa_required', True) is False:
            return None  # this login turned its own second factor off
        if any(request.path.startswith(prefix) for prefix in self.exempt_prefixes):
            return None
        return redirect('accounts:mfa_setup')


class SessionIdleTimeoutMiddleware(MiddlewareMixin):
    """End authenticated sessions idle longer than the configured timeout."""

    def process_view(
        self, request: HttpRequest, view_func: object, view_args: object, view_kwargs: object
    ) -> HttpResponse | None:
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated:
            return None
        idle_timeout = int(getattr(settings, 'SESSION_IDLE_TIMEOUT', 1800))
        if idle_timeout <= 0:
            return None
        now = time.time()
        last = request.session.get('last_activity')
        if last is not None:
            try:
                idle_for = now - float(last)
            except (TypeError, ValueError):
                idle_for = 0.0
            if idle_for > idle_timeout:
                from django.urls import reverse

                logout(request)
                minutes = max(1, idle_timeout // 60)
                return redirect(f'{reverse("accounts:login")}?timeout_minutes={minutes}')
        interval = int(getattr(settings, 'SESSION_IDLE_UPDATE_INTERVAL', 60))
        if last is None or (now - float(last)) >= interval:
            request.session['last_activity'] = now
        return None
