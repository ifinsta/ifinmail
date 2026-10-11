"""User management view."""

import csv
import logging
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.contrib.sessions.models import Session
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from backend.apps.accounts.services import UserService
from backend.apps.accounts.services.roles import RoleService
from backend.apps.accounts.services.sessions import UserSessionService
from backend.services.audit import AuditService

from ..types.permissions import PermissionCode
from .auth import require_perm

logger = logging.getLogger('backend')


def _initials(email: str) -> str:
    """Up-to-two-letter monogram from the mailbox's local part."""
    local = email.split('@', 1)[0]
    letters = [c for c in local if c.isalnum()]
    return (''.join(letters[:2]).upper() or '?')


def _admin_directory_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    live = UserSessionService.live_counts()
    for user in UserService.get_all_users():
        if not (user.is_staff or user.is_superuser):
            continue
        last_login = user.last_login.strftime('%Y-%m-%d %H:%M') if user.last_login else ''
        rows.append(
            {
                'name': user.email,
                'email': user.email,
                'initials': _initials(user.email),
                'role': RoleService.role_label(user),
                'status': 'Active' if user.is_active else 'Inactive',
                'last_active': user.last_login.isoformat() if user.last_login else '',
                'last': last_login,
                'live_sessions': str(live.get(user.email, 0)),
            }
        )
    return rows


def _failed_logins_24h() -> int:
    """Count failed sign-in attempts in the last 24 hours (django-axes)."""
    try:
        from axes.models import AccessAttempt

        since = timezone.now() - timedelta(hours=24)
        return AccessAttempt.objects.filter(success=False, attempt_time__gte=since).count()
    except Exception:  # pragma: no cover - axes optional / DB unavailable
        return 0


@login_required
@require_perm(PermissionCode.USERS_MANAGE)
def user_management(request: HttpRequest) -> HttpResponse:
    """User management and governance screen."""
    admins = _admin_directory_rows()
    now = timezone.now()
    active_sessions = Session.objects.filter(expire_date__gt=now).count()
    superuser_count = sum(1 for admin in admins if admin['role'] == 'Superuser')
    staff_count = sum(1 for admin in admins if admin['role'] == 'Staff')

    # Show the current session as a real live entry so the list never contradicts
    # the "Active Sessions" count with a false "No active sessions." empty state.
    live_sessions: list[dict[str, str]] = []
    if request.session.session_key:
        live_sessions.append(
            {
                'device': str(_('This device')),
                'detail': request.user.email if request.user.is_authenticated else '',
                'live': True,
                'ago': '',
            }
        )

    return render(
        request,
        'admin/user_management.html',
        {
            'active_section': 'users',
            'header_search_placeholder': 'Search users or permissions...',
            'show_user_profile': True,
            'admin_headers': [_('Administrator'), _('Role'), _('Status'), _('Last Active')],
            'admins': admins,
            'is_mock': False,
            'mfa_adoption_pct': '0%',
            'active_sessions': str(active_sessions),
            'session_domains': str(
                _('%(count)d valid session(s) on this server') % {'count': active_sessions}
            ),
            'failed_logins': str(_failed_logins_24h()),
            'rbac_status': str(_('Basic')),
            'unassigned_roles': str(_('Built-in roles only')),
            'role_counts': [
                {
                    'name': str(_('Superuser')),
                    'desc': str(_('Full system access')),
                    'count': str(_('%(count)d Users') % {'count': superuser_count}),
                    'badge_class': 'ifinmail-badge--info',
                },
                {
                    'name': str(_('Staff')),
                    'desc': str(_('Admin console access')),
                    'count': str(_('%(count)d Users') % {'count': staff_count}),
                    'badge_class': '',
                },
            ],
            'live_sessions': live_sessions,
            'governance_items': [],
            'anomaly_bars': [],
            'anomaly_description': '',
            'audit_stats': {
                'jit_access': str(_('Not configured')),
                'key_rotation': str(_('Not configured')),
                'manual_overrides': str(_('0 Pending Review')),
            },
        },
    )


@login_required
@require_perm(PermissionCode.USERS_MANAGE)
def users_export(request: HttpRequest) -> HttpResponse:
    """Export all users as a CSV download."""
    try:
        users = UserService.get_all_users()
    except Exception:
        users = []

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename=user_directory.csv'
    writer = csv.writer(response)
    writer.writerow(['Email', 'Role', 'Active', 'Staff', 'Superuser', 'Created'])
    for u in users:
        writer.writerow(
            [
                getattr(u, 'email', ''),
                'Admin' if getattr(u, 'is_staff', False) else 'User',
                'Yes' if getattr(u, 'is_active', False) else 'No',
                'Yes' if getattr(u, 'is_staff', False) else 'No',
                'Yes' if getattr(u, 'is_superuser', False) else 'No',
                getattr(u, 'created_at', ''),
            ]
        )
    AuditService.record(
        action='users_export',
        user=request.user.email if request.user.is_authenticated else None,
        detail=f'Exported {len(users)} users',
    )
    return response


@login_required
@require_perm(PermissionCode.USERS_MANAGE)
@require_POST
def users_kill_sessions(request: HttpRequest) -> JsonResponse:
    """Terminate all user sessions except the current one."""
    try:
        current_session_key = request.session.session_key
        # Flush all sessions from the database except the current one
        sessions = Session.objects.all()
        killed = 0
        if current_session_key:
            sessions = sessions.exclude(session_key=current_session_key)
        for session in sessions:
            session.delete()
            killed += 1

        AuditService.record(
            action='sessions_killed',
            user=request.user.email if request.user.is_authenticated else None,
            detail=f'Terminated {killed} sessions',
            severity='warning',
        )
        return JsonResponse(
            {'status': 'ok', 'killed': killed},
            content_type='application/json; charset=utf-8',
        )
    except Exception as e:
        logger.exception('Failed to kill sessions: %s', e)
        return JsonResponse(
            {'status': 'err', 'error': str(e)},
            status=500,
            content_type='application/json; charset=utf-8',
        )
