"""Per-mailbox profile page (web flow: views -> forms -> services).

Read-heavy detail to complement the mailbox table modal: identity, security
(sessions), activity (audit) and mail routing for one profile. All writes go
through the same services as the table actions — no duplicated logic.
"""

from __future__ import annotations

import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from backend.apps.accounts.models import MailUser, Role
from backend.apps.accounts.services.mfa import TOTPService
from backend.apps.accounts.services.roles import RoleError, RoleService
from backend.apps.accounts.services.sessions import SessionError, UserSessionService
from backend.apps.accounts.services.stepup import StepUpService
from backend.apps.accounts.services.tokens import TokenError, TokenService
from backend.apps.core.platform.services.audit import AuditService
from backend.apps.domains.services import DomainService
from backend.apps.mail.models import Alias, Mailbox
from backend.apps.mail.services import MailboxService

from ..forms.mailboxes import (
    MailboxActionForm,
    RoleChangeForm,
    SessionRevokeForm,
    TokenActionForm,
    TokenCreateForm,
)
from ..types.permissions import TOKEN_SCOPES, PermissionCode
from .auth import require_perm
from .mailboxes import _actor, _quota_budget_context, _quota_label

_PROFILE = require_perm(PermissionCode.MAIL_MANAGE)
_ACTIVITY_LIMIT = 50


def _get_mailbox(mailbox_id: uuid.UUID) -> Mailbox:
    mailbox = Mailbox.objects.select_related('domain').filter(id=mailbox_id).first()
    if mailbox is None:
        raise Http404('mailbox not found')
    return mailbox


@login_required
@_PROFILE
@require_GET
def mailbox_profile(request: HttpRequest, mailbox_id: uuid.UUID) -> HttpResponse:
    mailbox = _get_mailbox(mailbox_id)
    address = MailboxService.address_for(mailbox)
    user = MailUser.objects.filter(email=address).first()
    sessions = (
        UserSessionService.list_for_user(user, current_key=request.session.session_key)
        if user is not None
        else []
    )
    activity = AuditService.get_for_subject(address, _ACTIVITY_LIMIT)
    inbound_aliases = list(Alias.objects.filter(destination=address).order_by('source'))
    current_role = (
        Role.objects.filter(pk=user.role_id).first() if user is not None and user.role_id else None
    )
    pending = request.session.pop('invite_link', None)
    invite_link = (
        pending.get('link')
        if isinstance(pending, dict) and pending.get('address') == address
        else None
    )
    fresh_token = request.session.pop('api_token_plain', None)
    new_token_plain = (
        fresh_token.get('token')
        if isinstance(fresh_token, dict) and fresh_token.get('address') == address
        else None
    )
    return render(
        request,
        'admin/mailbox_profile.html',
        {
            'active_section': 'mailboxes',
            'show_settings_icon': True,
            'mailbox': mailbox,
            'address': address,
            'domain': mailbox.domain.name,
            'user': user,
            'is_admin': bool(user and (user.is_staff or user.is_superuser)),
            'is_active': bool(user and user.is_active),
            'invite_pending': bool(user is None or not user.has_usable_password()),
            'quota_label': _quota_label(mailbox.quota_bytes),
            'quota_mb': mailbox.quota_bytes // (1024 * 1024),
            'quota_budget': _quota_budget_context(),
            'created': mailbox.created_at.date().isoformat() if mailbox.created_at else '',
            'last_login': user.last_login if user and user.last_login else None,
            'sessions': sessions,
            'activity': activity,
            'inbound_aliases': inbound_aliases,
            'invite_link': invite_link,
            'mfa_status': TOTPService.status_for(user) if user is not None else None,
            'roles': RoleService.list_roles(),
            'current_role_key': current_role.key if current_role else '',
            'current_role_name': current_role.name if current_role else '',
            'can_grant_roles': RoleService.has_perm(request.user, 'roles.manage'),
            'tokens': TokenService.list_for(user) if user is not None else [],
            'token_scopes': list(TOKEN_SCOPES),
            'token_grantable': bool(user is not None and RoleService.effective_permissions(user)),
            'new_token_plain': new_token_plain,
            'domains': [d.name for d in DomainService.get_all_domains()],
            'action_choices': [a for a in MailboxActionForm.ACTIONS if a != 'invite'],
        },
    )


@login_required
@_PROFILE
@require_POST
def mailbox_sessions_action(request: HttpRequest, mailbox_id: uuid.UUID) -> HttpResponse:
    form = SessionRevokeForm(request.POST)
    if not form.is_valid() or str(form.cleaned_data['mailbox_id']) != str(mailbox_id):
        messages.error(request, 'That session request could not be read.')
        return redirect('accounts:mailbox_profile', mailbox_id=mailbox_id)
    mailbox = _get_mailbox(mailbox_id)
    address = MailboxService.address_for(mailbox)
    user = MailUser.objects.filter(email=address).first()
    if user is None:
        messages.error(request, f'{address} has no login to revoke sessions for.')
        return redirect('accounts:mailbox_profile', mailbox_id=mailbox_id)
    try:
        if form.cleaned_data['revoke_all']:
            killed = UserSessionService.revoke_all(user, except_key=request.session.session_key)
            message = (
                f'Ended {killed} session(s) for {address}.'
                if killed
                else f'{address} has no other live sessions.'
            )
            AuditService.record(
                action='mailbox_sessions_killed', user=_actor(request), detail=address
            )
        else:
            key = form.cleaned_data['session_key']
            if key == (request.session.session_key or ''):
                raise SessionError('That is the session you are using right now.')
            if not UserSessionService.revoke(user, key):
                raise SessionError('That session is already gone.')
            message = f'Ended one session for {address}.'
            AuditService.record(
                action='mailbox_session_revoked', user=_actor(request), detail=address
            )
    except SessionError as exc:
        messages.error(request, str(exc))
        return redirect('accounts:mailbox_profile', mailbox_id=mailbox_id)
    messages.success(request, message)
    return redirect('accounts:mailbox_profile', mailbox_id=mailbox_id)


@login_required
@require_perm(PermissionCode.ROLES_MANAGE)
@require_POST
def mailbox_role_action(request: HttpRequest, mailbox_id: uuid.UUID) -> HttpResponse:
    """Assign (or clear) one profile's role. Only role-holders may grant roles."""
    form = RoleChangeForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'That role request could not be read.')
        return redirect('accounts:mailbox_profile', mailbox_id=mailbox_id)
    mailbox = _get_mailbox(mailbox_id)
    address = MailboxService.address_for(mailbox)
    if (form.cleaned_data['address'] or '').strip().lower() != address:
        messages.error(request, 'That role request does not match this profile.')
        return redirect('accounts:mailbox_profile', mailbox_id=mailbox_id)
    user = MailUser.objects.filter(email=address).first()
    if user is None:
        messages.error(request, f'{address} has no login to assign a role to.')
        return redirect('accounts:mailbox_profile', mailbox_id=mailbox_id)
    if user.pk == request.user.pk:
        messages.error(request, 'Your own role cannot be changed here.')
        return redirect('accounts:mailbox_profile', mailbox_id=mailbox_id)
    problem = StepUpService.confirm(request)
    if problem:
        messages.error(request, problem)
        return redirect('accounts:mailbox_profile', mailbox_id=mailbox_id)
    try:
        role = RoleService.assign(user, form.cleaned_data['role'] or None)
    except RoleError as exc:
        messages.error(request, str(exc))
        return redirect('accounts:mailbox_profile', mailbox_id=mailbox_id)
    AuditService.record(
        action='role_assigned',
        user=_actor(request),
        detail=f'{address} -> {role.key if role else "legacy"}',
    )
    messages.success(
        request,
        f'{address} is now {role.name}.' if role else f'{address} is back to legacy access.',
    )
    return redirect('accounts:mailbox_profile', mailbox_id=mailbox_id)


def _token_owner(mailbox_id: uuid.UUID, address: str) -> tuple[Mailbox, str, MailUser | None]:
    mailbox = _get_mailbox(mailbox_id)
    full = MailboxService.address_for(mailbox)
    if address != full:
        raise TokenError('That token request does not match this profile.')
    return mailbox, full, MailUser.objects.filter(email=full).first()


@login_required
@_PROFILE
@require_POST
def mailbox_token_create(request: HttpRequest, mailbox_id: uuid.UUID) -> HttpResponse:
    form = TokenCreateForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'That token request could not be read.')
        return redirect('accounts:mailbox_profile', mailbox_id=mailbox_id)
    problem = StepUpService.confirm(request)
    if problem:
        messages.error(request, problem)
        return redirect('accounts:mailbox_profile', mailbox_id=mailbox_id)
    try:
        _, address, user = _token_owner(mailbox_id, form.cleaned_data['address'].lower())
        if user is None:
            raise TokenError(f'{address} has no login to mint a token for.')
        row, plain = TokenService.create(
            user,
            form.cleaned_data['name'],
            list(form.cleaned_data['scopes'] or []),
            expires_in_days=form.cleaned_data['expires_in_days'],
        )
    except TokenError as exc:
        messages.error(request, str(exc))
        return redirect('accounts:mailbox_profile', mailbox_id=mailbox_id)
    request.session['api_token_plain'] = {'address': address, 'token': plain}
    AuditService.record(
        action='api_token_created',
        user=_actor(request),
        detail=f'{address} {row.prefix} scopes={",".join(row.scopes)}',
    )
    messages.success(
        request, f'Token {row.name} created for {address} — copy it below. It is shown once.'
    )
    return redirect('accounts:mailbox_profile', mailbox_id=mailbox_id)


@login_required
@_PROFILE
@require_POST
def mailbox_token_action(request: HttpRequest, mailbox_id: uuid.UUID) -> HttpResponse:
    form = TokenActionForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'That token request could not be read.')
        return redirect('accounts:mailbox_profile', mailbox_id=mailbox_id)
    try:
        _, address, user = _token_owner(mailbox_id, form.cleaned_data['address'].lower())
        if user is None:
            raise TokenError(f'{address} has no tokens to manage.')
        token_id = str(form.cleaned_data['token_id'])
        if form.cleaned_data['action'] == 'rotate':
            row, plain = TokenService.rotate(user, token_id)
            request.session['api_token_plain'] = {'address': address, 'token': plain}
            AuditService.record(
                action='api_token_rotated', user=_actor(request), detail=f'{address} {row.prefix}'
            )
            messages.success(request, f'Token {row.name} rotated — copy the new secret below.')
        else:
            if not TokenService.revoke(user, token_id):
                raise TokenError('That token is already gone.')
            AuditService.record(action='api_token_revoked', user=_actor(request), detail=address)
            messages.success(request, f'Token revoked for {address}.')
    except TokenError as exc:
        messages.error(request, str(exc))
    return redirect('accounts:mailbox_profile', mailbox_id=mailbox_id)
