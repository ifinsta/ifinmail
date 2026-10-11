"""Neutral, provider-independent permission codes for the admin console.

Design notes (deliberate, keep them):
* Codes are coarse *areas*, not per-button flags — ~9 codes cover ~60 views.
  Finer splits can be added without touching the model (permissions is a list).
* Codes say nothing about any identity provider. A future OIDC login maps
  IdP groups/claims onto local Role rows; enforcement never reads the IdP.
* Legacy mapping lives in ``RoleService`` (staff without a role keeps full
  access), so existing installs and tests keep working unchanged.
"""

from __future__ import annotations

from enum import StrEnum


class PermissionCode(StrEnum):
    """Every permission the console checks (``area.action``)."""

    CONSOLE_ACCESS = 'console.access'  # open the dashboard / settings hub
    MAIL_MANAGE = 'mail.manage'  # mailboxes, aliases, profiles, mailbox MFA
    DNS_MANAGE = 'dns.manage'  # zones, records, provider push, delegation
    SECURITY_MANAGE = 'security.manage'  # firewall, TLS, spam policy
    SYSTEM_MANAGE = 'system.manage'  # branding, maintenance actions, shell
    USERS_MANAGE = 'users.manage'  # directory, export, session kills
    AUDIT_VIEW = 'audit.view'  # logs, telemetry, activity trails (read-only)
    ROLES_MANAGE = 'roles.manage'  # grant roles (keys to the kingdom)
    SETUP_MANAGE = 'setup.manage'  # setup wizard steps


ALL_PERMISSIONS: tuple[str, ...] = tuple(code.value for code in PermissionCode)

# Codes an API token may carry. Access-administration codes are excluded on
# purpose: a token must never grant roles or drive the setup wizard, so a
# leaked token cannot be escalated into broader access.
TOKEN_SCOPES: tuple[str, ...] = tuple(
    code.value
    for code in PermissionCode
    if code not in (PermissionCode.ROLES_MANAGE, PermissionCode.SETUP_MANAGE)
)

# -- seed roles (mirrored in migration 0003; keep in sync) -----------------------


def _all(*, without: tuple[str, ...] = ()) -> list[str]:
    return [code for code in ALL_PERMISSIONS if code not in without]


SEED_ROLES: tuple[dict[str, object], ...] = (
    {
        'key': 'owner',
        'name': 'Owner',
        'description': 'Full access, including role grants. Keep to one or two logins.',
        'permissions': _all(),
        'is_system': True,
    },
    {
        'key': 'administrator',
        'name': 'Administrator',
        'description': 'Runs the mail system day to day. Cannot grant roles.',
        'permissions': _all(without=(PermissionCode.ROLES_MANAGE.value,)),
        'is_system': True,
    },
    {
        'key': 'support',
        'name': 'Support',
        'description': 'Read-only triage: dashboard plus logs and audit trails.',
        'permissions': [
            PermissionCode.CONSOLE_ACCESS.value,
            PermissionCode.AUDIT_VIEW.value,
        ],
        'is_system': True,
    },
)


# -- view mapping (which gate guards which surface) --------------------------------
#
# dashboard GET, settings hub, MFA enrollment -> console.access
# mailboxes / aliases / profiles / mailbox MFA + sessions -> mail.manage
# dns (web, server pages, provider API) -> dns.manage
# certificates, network/firewall, spam policy -> security.manage
# branding, dashboard maintenance POSTs (rescan/shell/purge/reboot) -> system.manage
# user directory, export, session kills -> users.manage
# logs, telemetry API, per-profile activity -> audit.view
# role assignment -> roles.manage
# setup wizard -> setup.manage
