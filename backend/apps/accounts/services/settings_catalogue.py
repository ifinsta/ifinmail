"""The Settings hub catalogue: every grouped settings page in one place."""

from __future__ import annotations

from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from ..types.settings import (
    SettingsGroup,
    SettingsGroupKey,
    SettingsIcon,
    SettingsItem,
)

# Pages that already existed keep their URL names; new pages share one route.
_PAGE = 'accounts:settings_page'

CATALOGUE: tuple[SettingsGroup, ...] = (
    SettingsGroup(
        SettingsGroupKey.WORKSPACE,
        _('Workspace'),
        (
            SettingsItem(
                'general',
                _('General'),
                _('Name, logo, favicon, colours and fonts.'),
                SettingsIcon.GENERAL,
                'accounts:branding_identity',
                ('branding', 'identity', 'logo', 'favicon', 'colour', 'color', 'font'),
            ),
            SettingsItem(
                'dns',
                _('Domains & DNS'),
                _('Add domains, DNS provider and record export.'),
                SettingsIcon.DOMAINS,
                'dns:config',
                ('domain', 'dns', 'mx', 'spf', 'dkim', 'dmarc', 'provider', 'cloudflare'),
            ),
            SettingsItem(
                'dnsserver',
                _('DNS server'),
                _('Authoritative zones, custom records and DNSSEC.'),
                SettingsIcon.DOMAINS,
                'dns:server',
                ('dns', 'zone', 'nameserver', 'ns', 'dnssec', 'ds', 'record', 'glue', 'authoritative', 'secondary'),
            ),
            SettingsItem(
                'mail',
                _('Mail server'),
                _('Hostname, relay and outgoing delivery.'),
                SettingsIcon.MAIL,
                _PAGE,
                ('smtp', 'relay', 'smart host', 'hostname', 'outgoing', 'mta-sts'),
                {'slug': 'mail'},
            ),
            SettingsItem(
                'deliverability',
                _('Deliverability'),
                _('Blocklists, resolvers and signing keys.'),
                SettingsIcon.DELIVERABILITY,
                _PAGE,
                ('rbl', 'blocklist', 'dkim', 'selector', 'resolver', 'reputation'),
                {'slug': 'deliverability'},
            ),
            SettingsItem(
                'spam',
                _('Spam filtering'),
                _('Sensitivity and DNSBL providers.'),
                SettingsIcon.SPAM,
                'accounts:spam_filtering',
                ('spam', 'filter', 'rspamd', 'dnsbl', 'sensitivity'),
            ),
        ),
    ),
    SettingsGroup(
        SettingsGroupKey.ACCESS,
        _('Access'),
        (
            SettingsItem(
                'mailboxes',
                _('Mailboxes'),
                _('Create mailboxes, passwords and quotas.'),
                SettingsIcon.MAIL,
                'accounts:mailboxes',
                ('mailbox', 'account', 'password', 'quota', 'registration', 'sign up'),
            ),
            SettingsItem(
                'aliases',
                _('Aliases'),
                _('Forward addresses to other addresses.'),
                SettingsIcon.DELIVERABILITY,
                'accounts:aliases',
                ('alias', 'forward', 'postmaster', 'abuse'),
            ),
            SettingsItem(
                'users',
                _('Users'),
                _('Mailboxes, roles and active sessions.'),
                SettingsIcon.USERS,
                'accounts:user_management',
                ('user', 'mailbox', 'account', 'session', 'role'),
            ),
            SettingsItem(
                'security',
                _('Security'),
                _('Sign-in protection, cookies and transport policy.'),
                SettingsIcon.SECURITY,
                _PAGE,
                ('lockout', 'password', 'hsts', 'csp', 'cookie', 'https', 'axes'),
                {'slug': 'security'},
            ),
            SettingsItem(
                'certificates',
                _('TLS certificates'),
                _('Issue, renew or upload the server certificate.'),
                SettingsIcon.CERTIFICATE,
                'accounts:certificates',
                ('tls', 'ssl', 'certificate', 'letsencrypt', 'renew', 'https', 'custom certificate', 'expiry'),
            ),
            SettingsItem(
                'network',
                _('Network & entry points'),
                _('Open ports, blocked networks and connection limits.'),
                SettingsIcon.NETWORK,
                'accounts:network',
                ('firewall', 'port', 'smtp', 'imap', 'block', 'ip', 'rate limit', 'entry', 'access'),
            ),
        ),
    ),
    SettingsGroup(
        SettingsGroupKey.PERSONALIZATION,
        _('Personalization'),
        (
            SettingsItem(
                'appearance',
                _('Appearance'),
                _('Light, dark, auto and high contrast.'),
                SettingsIcon.APPEARANCE,
                _PAGE,
                ('theme', 'dark', 'light', 'contrast', 'mode'),
                {'slug': 'appearance'},
            ),
            SettingsItem(
                'language',
                _('Language & region'),
                _('Interface language and time zone.'),
                SettingsIcon.LANGUAGE,
                _PAGE,
                ('locale', 'timezone', 'time zone', 'translation'),
                {'slug': 'language'},
            ),
        ),
    ),
    SettingsGroup(
        SettingsGroupKey.SYSTEM,
        _('System'),
        (
            SettingsItem(
                'logs',
                _('Logs'),
                _('Live infrastructure and audit telemetry.'),
                SettingsIcon.LOGS,
                'accounts:logs',
                ('log', 'audit', 'telemetry', 'export'),
            ),
            SettingsItem(
                'monitoring',
                _('Logging & monitoring'),
                _('Log levels and error reporting.'),
                SettingsIcon.MONITORING,
                _PAGE,
                ('sentry', 'level', 'debug', 'health', 'errors'),
                {'slug': 'monitoring'},
            ),
            SettingsItem(
                'storage',
                _('Storage & certificates'),
                _('Mail store and disk checks.'),
                SettingsIcon.STORAGE,
                _PAGE,
                ('disk', 'tls', 'certificate', 'letsencrypt', 'media', 'vhosts'),
                {'slug': 'storage'},
            ),
            SettingsItem(
                'backups',
                _('Backups & scheduled jobs'),
                _('Backup status and automatic checks.'),
                SettingsIcon.STORAGE,
                _PAGE,
                ('backup', 'restore', 'gpg', 'schedule', 'job', 'cron', 'verify'),
                {'slug': 'backups'},
            ),
            SettingsItem(
                'maintenance',
                _('Maintenance'),
                _('Rescan health and prune archived logs.'),
                SettingsIcon.MAINTENANCE,
                _PAGE,
                ('rescan', 'purge', 'restart', 'reboot', 'cleanup'),
                {'slug': 'maintenance'},
            ),
            SettingsItem(
                'about',
                _('About'),
                _('Version, environment and shortcuts.'),
                SettingsIcon.ABOUT,
                _PAGE,
                ('version', 'environment', 'shortcuts', 'support', 'docs'),
                {'slug': 'about'},
            ),
        ),
    ),
)

# Slugs served by the generic ``accounts:settings_page`` route.
PAGE_SLUGS: frozenset[str] = frozenset(
    item.url_kwargs['slug'] for group in CATALOGUE for item in group.items if item.url_kwargs
)


class SettingsCatalogue:
    @staticmethod
    def groups() -> tuple[SettingsGroup, ...]:
        return CATALOGUE

    @staticmethod
    def items() -> list[SettingsItem]:
        return [item for group in CATALOGUE for item in group.items]

    @staticmethod
    def get(key: str) -> SettingsItem | None:
        return next((i for i in SettingsCatalogue.items() if i.key == key), None)

    @staticmethod
    def url_for(item: SettingsItem) -> str:
        return reverse(item.url_name, kwargs=item.url_kwargs or None)
