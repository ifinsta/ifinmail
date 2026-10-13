"""Staff session guards: first-password change, MFA enforcement + idle timeout.

SetupRequiredMiddleware sends every web page to the setup wizard until first-run setup is
finished (signing in first when needed). Mail clients, health checks and the API are unaffected.

PasswordChangeEnforcementMiddleware routes a login flagged ``password_change_required`` (the
administrator the installer created, whose password was printed) to the first-password page
before anything else, including MFA enrollment.

MFAEnforcementMiddleware offers two-factor enrollment to staff sessions without MFA
proof (``mfa_verified_at``); people who have not set it up can postpone the prompt a week — including sessions established
before MFA shipped. Exempt paths keep enrollment, logout, login, the setup
wizard and non-console endpoints reachable.

SessionIdleTimeoutMiddleware ends sessions idle longer than
``SESSION_IDLE_TIMEOUT`` (default 30 min). Activity timestamps update at most
once a minute to avoid a session write on every request.
"""

from __future__ import annotations

import re
import time

from django.conf import settings
from django.contrib.auth import logout
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils.deprecation import MiddlewareMixin

FIRST_PASSWORD_PATH = '/accounts/first-password/'


class PasswordChangeEnforcementMiddleware(MiddlewareMixin):
    exempt_prefixes = (
        FIRST_PASSWORD_PATH,
        '/accounts/logout/',
        '/accounts/login/',
        '/health',
        '/static/',
        '/media/',
    )

    def process_view(
        self, request: HttpRequest, view_func: object, view_args: object, view_kwargs: object
    ) -> HttpResponse | None:
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated:
            return None
        if not getattr(user, 'password_change_required', False):
            return None
        if any(request.path.startswith(prefix) for prefix in self.exempt_prefixes):
            return None
        return redirect('accounts:first_password')


class SetupRequiredMiddleware(MiddlewareMixin):
    """Until setup is finished, every page leads to the setup wizard.

    The wizard requires an administrator, so a visitor who is not signed in lands on the login
    page first (``?next=`` the wizard). Paths that machines use (mail client autoconfiguration,
    MTA-STS, health checks, the API) and the steps of signing in are never redirected.
    """

    exempt_prefixes = (
        '/accounts/setup/',
        '/accounts/login/',
        '/accounts/logout/',
        FIRST_PASSWORD_PATH,
        '/accounts/mfa/',
        '/accounts/password-reset/',
        '/accounts/mailbox-setup/',
        '/health',
        '/static/',
        '/media/',
        '/api/',
        '/csp-report/',
        '/telemetry/',
        '/manifest.webmanifest',
        '/.well-known/',
        '/mail/config-v1.1.xml',
        '/autodiscover/',
        '/Autodiscover/',
    )

    def __init__(self, get_response: object) -> None:
        super().__init__(get_response)
        self._setup_done = False  # setup never becomes unfinished again; stop asking once done

    def process_view(
        self, request: HttpRequest, view_func: object, view_args: object, view_kwargs: object
    ) -> HttpResponse | None:
        if self._setup_done or not getattr(settings, 'SETUP_REQUIRED_REDIRECT', True):
            return None
        if any(request.path.startswith(prefix) for prefix in self.exempt_prefixes):
            return None
        from backend.apps.accounts.services.setup_state import SetupState

        if SetupState.is_complete():
            self._setup_done = True
            return None
        return redirect('accounts:setup_wizard')


class ApiResponseHeadersMiddleware:
    """Headers every API response carries, whichever version or endpoint produced it.

    * ``X-API-Version`` — the version in the URL (``/api/v1/...`` is ``1``), so a logged
      response says which contract it followed.
    * ``Cache-Control: no-store`` — responses can hold mailbox data; nothing should keep a copy.
    * ``X-RateLimit-*`` and ``Retry-After`` — the caller's budget, when the call was metered.
    * ``WWW-Authenticate`` on a 401, so clients know both ways to present a key.
    """

    _VERSION = re.compile(r'^/api/v(\d+)/')

    def __init__(self, get_response: object) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        if not request.path.startswith('/api/'):
            return response
        match = self._VERSION.match(request.path)
        if match:
            response['X-API-Version'] = match.group(1)
        response['Cache-Control'] = 'no-store'
        state = getattr(request, 'api_rate', None)
        if state is not None:
            response['X-RateLimit-Limit'] = str(state.limit)
            response['X-RateLimit-Remaining'] = str(state.remaining)
            response['X-RateLimit-Reset'] = str(state.reset_in)
            if response.status_code == 429:
                response['Retry-After'] = str(state.reset_in)
        if response.status_code == 401:
            response['WWW-Authenticate'] = 'Basic realm="ifinmail API", Bearer realm="ifinmail API"'
        return response


class MFAEnforcementMiddleware(MiddlewareMixin):
    exempt_prefixes = (
        FIRST_PASSWORD_PATH,  # the new password comes first, enrollment right after
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
        from backend.apps.accounts.services.mfa import TOTPService

        if getattr(user, 'mfa_required', True) is False and not TOTPService.enforced():
            return None  # this login turned its own second factor off (optional policy only)
        if any(request.path.startswith(prefix) for prefix in self.exempt_prefixes):
            return None
        if TOTPService.has_verified_device(user):
            return redirect('accounts:mfa_setup')  # enrolled, but this session never proved it
        if not TOTPService.prompt_due(user):
            return None  # setup is optional: "Remind me in a week" is running
        return redirect('accounts:mfa_setup')


class FormEndpointGetMiddleware(MiddlewareMixin):
    """A browser GET on a form-only (POST) URL goes to the page the form lives on.

    Reloading or going back to a URL a form posted to (or reaching it through a login
    ``?next=``) used to show a bare "HTTP ERROR 405". The nearest parent path that exists is
    the page the form lives on (``.../mailboxes/registration/`` → ``.../mailboxes/``).
    API clients and non-HTML requests keep the 405.
    """

    def process_response(self, request: HttpRequest, response: HttpResponse) -> HttpResponse:
        if response.status_code != 405 or request.method not in ('GET', 'HEAD'):
            return response
        if request.path.startswith('/api/') or 'text/html' not in request.headers.get('Accept', ''):
            return response
        from django.urls import Resolver404, resolve, reverse

        parts = [p for p in request.path.split('/') if p]
        while len(parts) > 1:
            parts.pop()
            candidate = '/' + '/'.join(parts) + '/'
            try:
                resolve(candidate)
            except Resolver404:
                continue
            return redirect(candidate)
        return redirect(reverse('accounts:dashboard'))


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
