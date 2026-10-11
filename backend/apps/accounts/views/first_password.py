"""First sign-in of the installer's administrator: replace the printed password.

``PasswordChangeEnforcementMiddleware`` sends a login flagged ``password_change_required`` here
before any other console page. Afterwards the usual order resumes: setup wizard, then MFA
enrollment (``MFAEnforcementMiddleware``).
"""

from __future__ import annotations

from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from backend.apps.accounts.services.initial_admin import InitialAdminService
from backend.apps.accounts.services.profile import MIN_PASSWORD_LENGTH, ProfileError
from backend.apps.accounts.services.setup_state import SetupState
from backend.apps.core.platform.services.audit import AuditService

from .auth import _get_client_ip


@login_required
def first_password(request: HttpRequest) -> HttpResponse:
    user = request.user
    if not getattr(user, 'password_change_required', False):
        return redirect('accounts:dashboard')

    error = ''
    if request.method == 'POST':
        try:
            InitialAdminService.set_first_password(
                user,
                request.POST.get('new_password1', ''),
                request.POST.get('new_password2', ''),
            )
        except ProfileError as exc:
            error = str(exc)
        else:
            update_session_auth_hash(request, user)  # stay signed in with the new password
            AuditService.record(
                'initial_password_changed',
                user=user.email,
                detail=f'IP: {_get_client_ip(request)}',
                severity='info',
            )
            if (user.is_staff or user.is_superuser) and not SetupState.is_complete():
                return redirect('accounts:setup_wizard')
            return redirect('accounts:dashboard')

    return render(
        request,
        'admin/first_password.html',
        {'error': error, 'email': user.email, 'min_length': MIN_PASSWORD_LENGTH},
    )
