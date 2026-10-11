"""Role-based access: neutral roles, effective permissions, guarded assignment.

Neutrality contract: roles and permission codes are local concepts. A future
SSO login maps IdP groups/claims onto Role rows here; enforcement below never
reads the identity provider.

Legacy mapping (back-compat, no flag day): active superusers hold every
permission; active staff *without* a role hold every permission except none —
i.e. today's behavior. Assigning a role narrows staff to that role's codes.
"""

from __future__ import annotations

import logging

from django.db import transaction

from backend.apps.accounts.models import MailUser, Role
from backend.apps.accounts.types.permissions import ALL_PERMISSIONS

logger = logging.getLogger('backend')

_MANAGE_ROLES = 'roles.manage'


class RoleError(ValueError):
    """A role request that cannot be fulfilled (message is user-safe)."""


class RoleService:
    @staticmethod
    def ensure_seed() -> None:
        """Create any missing system roles (idempotent; safe to call anywhere)."""
        from backend.apps.accounts.types.permissions import SEED_ROLES

        for row in SEED_ROLES:
            Role.objects.update_or_create(
                key=row['key'],
                defaults={
                    'name': row['name'],
                    'description': row['description'],
                    'permissions': list(row['permissions']),
                    'is_system': row['is_system'],
                },
            )

    @staticmethod
    def list_roles() -> list[Role]:
        return list(Role.objects.order_by('name'))

    @staticmethod
    def get_by_key(key: str) -> Role | None:
        return Role.objects.filter(key=(key or '').strip().lower()).first()

    @staticmethod
    def effective_permissions(user: MailUser | None) -> set[str]:
        """Permission codes ``user`` holds (empty for anonymous/inactive)."""
        if user is None or not getattr(user, 'is_authenticated', False):
            return set()
        try:
            active = bool(user.is_active)
            superuser = bool(user.is_superuser)
            staff = bool(user.is_staff)
        except Exception:
            return set()
        if not active:
            return set()
        if superuser:
            return set(ALL_PERMISSIONS)
        if not staff:
            return set()
        role_id = getattr(user, 'role_id', None)
        if not role_id:
            return set(ALL_PERMISSIONS)  # legacy staff: unchanged behavior
        try:
            role = Role.objects.filter(pk=role_id).first()
        except Exception:
            logger.exception('Role lookup failed')
            return set()
        if role is None:
            return set(ALL_PERMISSIONS)  # dangling reference: fail open to legacy
        codes = role.permissions if isinstance(role.permissions, list) else []
        return {str(code) for code in codes if str(code) in ALL_PERMISSIONS}

    @staticmethod
    def has_perm(user: MailUser | None, code: str) -> bool:
        return code in RoleService.effective_permissions(user)

    @staticmethod
    def _holders_of(code: str, *, exclude_pk: object = None) -> bool:
        """True when someone other than ``exclude_pk`` effectively holds ``code``."""
        qs = MailUser.objects.filter(is_active=True)
        if exclude_pk is not None:
            qs = qs.exclude(pk=exclude_pk)
        for candidate in qs.only('pk', 'is_superuser', 'is_staff', 'role_id'):
            if code in RoleService.effective_permissions(candidate):
                return True
        return False

    @staticmethod
    @transaction.atomic
    def assign(user: MailUser, key: str | None) -> MailUser | None:
        """Set ``user``'s role (None clears to legacy staff). Guards the last key-holder."""
        target_key = (key or '').strip().lower() or None
        role = RoleService.get_by_key(target_key) if target_key else None
        if target_key and role is None:
            raise RoleError(f'There is no role called {target_key!r}.')
        current = RoleService.effective_permissions(user)
        future = (
            set(ALL_PERMISSIONS)
            if (user.is_superuser or role is None)
            else {str(c) for c in (role.permissions or []) if str(c) in ALL_PERMISSIONS}
        )
        if (
            _MANAGE_ROLES in current
            and _MANAGE_ROLES not in future
            and not RoleService._holders_of(_MANAGE_ROLES, exclude_pk=user.pk)
        ):
            raise RoleError('This is the last login that can grant roles.')
        user.role = role
        user.save(update_fields=['role'])
        return role

    @staticmethod
    def role_label(user: MailUser | None) -> str:
        """Human role for display: superuser/staff/role-name/user."""
        if user is None:
            return ''
        if getattr(user, 'is_superuser', False):
            return 'Superuser'
        role_id = getattr(user, 'role_id', None)
        if role_id:
            role = Role.objects.filter(pk=role_id).first()
            if role is not None:
                return role.name
        if getattr(user, 'is_staff', False):
            return 'Staff'
        return 'User'
