"""accounts views package — re-exports all public view functions."""

from .account import account_name, account_page, account_password
from .auth import login_view, logout_view
from .branding import branding_identity, branding_reset, branding_save
from .dashboard import (
    dashboard,
    dashboard_log_purge,
    dashboard_reboot,
    dashboard_rescan,
    dashboard_shell,
)
from .logs import logs, logs_export, logs_full_history, logs_live_data, logs_report, logs_trace
from .mailboxes import (
    aliases_create,
    aliases_delete,
    aliases_page,
    mailbox_setup,
    mailboxes_action,
    mailboxes_create,
    mailboxes_page,
    registration_toggle,
)
from .first_password import first_password
from .system_health import system_health, system_health_recheck, system_health_updates
from .mfa import mailbox_mfa_reset, mfa_setup, mfa_verify
from .password_reset import (
    password_reset,
    password_reset_complete,
    password_reset_confirm,
    password_reset_done,
)
from .profile import (
    mailbox_profile,
    mailbox_role_action,
    mailbox_sessions_action,
    mailbox_token_action,
    mailbox_token_create,
)
from .registration import (
    check_username_availability,
    step_complete,
    step_password,
    step_profile,
    step_username,
    step_verify,
    step_verify_confirm,
)
from .settings_hub import settings_hub, settings_page
from .setup import setup_advance, setup_step, setup_wizard
from .spam import spam_add_provider, spam_filtering, spam_set_sensitivity
from .users import user_management, users_export, users_kill_sessions

__all__ = [
    'account_name',
    'account_page',
    'account_password',
    'aliases_create',
    'aliases_delete',
    'aliases_page',
    'mailbox_setup',
    'mailbox_profile',
    'mailbox_role_action',
    'mailbox_sessions_action',
    'mailbox_token_action',
    'mailbox_token_create',
    'mailbox_mfa_reset',
    'mailboxes_action',
    'mailboxes_create',
    'mailboxes_page',
    'first_password',
    'system_health',
    'system_health_recheck',
    'system_health_updates',
    'mfa_setup',
    'mfa_verify',
    'registration_toggle',
    'branding_identity',
    'branding_reset',
    'branding_save',
    'check_username_availability',
    'dashboard',
    'dashboard_log_purge',
    'dashboard_reboot',
    'dashboard_rescan',
    'dashboard_shell',
    'login_view',
    'logout_view',
    'logs',
    'logs_export',
    'logs_full_history',
    'logs_live_data',
    'logs_report',
    'logs_trace',
    'password_reset',
    'password_reset_complete',
    'password_reset_confirm',
    'password_reset_done',
    'settings_hub',
    'settings_page',
    'setup_advance',
    'setup_step',
    'setup_wizard',
    'spam_add_provider',
    'spam_filtering',
    'spam_set_sensitivity',
    'step_complete',
    'step_password',
    'step_profile',
    'step_username',
    'step_verify',
    'step_verify_confirm',
    'user_management',
    'users_export',
    'users_kill_sessions',
]
