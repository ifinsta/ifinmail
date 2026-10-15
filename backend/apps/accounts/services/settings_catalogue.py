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
                'website',
                _('Website'),
                _('Which public pages are shown, and the words on them.'),
                SettingsIcon.GENERAL,
                'accounts:website_pages',
                ('website', 'page', 'pages', 'landing', 'marketing', 'footer', 'powered by', 'content'),
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
                (
                    'dns',
                    'zone',
                    'nameserver',
                    'ns',
                    'dnssec',
                    'ds',
                    'record',
                    'glue',
                    'authoritative',
                    'secondary',
                ),
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
                'passkeys',
                _('Passkeys'),
                _('Sign in with a fingerprint, face or security key instead of a password.'),
                SettingsIcon.SECURITY,
                'accounts:passkeys',
                ('passkey', 'webauthn', 'fido', 'biometric', 'security key', 'passwordless', 'mfa'),
            ),
            SettingsItem(
                'api-keys',
                _('API keys'),
                _('Keys and secrets for integrations that call the API.'),
                SettingsIcon.SECURITY,
                'accounts:api_keys',
                ('api', 'key', 'secret', 'token', 'integration', 'webhook', 'automation', 'v1'),
            ),
            SettingsItem(
                'approvals',
                _('Approvals'),
                _('Mail from agents that waits for a person before it leaves.'),
                SettingsIcon.SECURITY,
                'accounts:approvals',
                ('approval', 'approve', 'agent', 'held', 'pending', 'human', 'review'),
            ),
            SettingsItem(
                'suppressions',
                _('Suppressions'),
                _('Recipients API mail never goes to: bounced, unsubscribed, added.'),
                SettingsIcon.DELIVERABILITY,
                'accounts:suppressions',
                ('suppression', 'unsubscribe', 'bounce', 'bounced', 'list', 'compliance', 'gmail'),
            ),
            SettingsItem(
                'webhooks',
                _('Webhooks'),
                _('Signed events for your applications: delivery outcomes, received mail.'),
                SettingsIcon.SECURITY,
                'accounts:webhooks',
                ('webhook', 'event', 'events', 'callback', 'bounce', 'delivered', 'integration'),
            ),
            SettingsItem(
                'certificates',
                _('TLS certificates'),
                _('Issue, renew or upload the server certificate.'),
                SettingsIcon.CERTIFICATE,
                'accounts:certificates',
                (
                    'tls',
                    'ssl',
                    'certificate',
                    'letsencrypt',
                    'renew',
                    'https',
                    'custom certificate',
                    'expiry',
                ),
            ),
            SettingsItem(
                'network',
                _('Network & entry points'),
                _('Open ports, blocked networks and connection limits.'),
                SettingsIcon.NETWORK,
                'accounts:network',
                (
                    'firewall',
                    'port',
                    'smtp',
                    'imap',
                    'block',
                    'ip',
                    'rate limit',
                    'entry',
                    'access',
                ),
            ),
        ),
    ),
    SettingsGroup(
        SettingsGroupKey.PERSONALIZATION,
        _('Personalization'),
        (
            SettingsItem(
                'account',
                _('Account'),
                _('Your display name, password and sign-in security.'),
                SettingsIcon.ACCOUNT,
                'accounts:account',
                ('profile', 'name', 'display name', 'password', 'mfa', 'two-factor', 'account'),
            ),
            SettingsItem(
                'appearance',
                _('Appearance'),
                _('Smooth, light, dark, auto and high contrast.'),
                SettingsIcon.APPEARANCE,
                _PAGE,
                ('theme', 'dark', 'light', 'contrast', 'mode'),
                {'slug': 'appearance'},
            ),
            SettingsItem(
                'language',
                _('Language & region'),
                _('Interface language and time zone (read-only, set at deployment).'),
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
                'threats',
                _('Threats'),
                _('Scanners and attacks, and where to tighten.'),
                SettingsIcon.SECURITY,
                'accounts:threats',
                ('threat', 'scan', 'attack', 'probe', 'ddos', 'dos', 'brute', 'block', 'nginx'),
            ),
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
                'releases',
                _('App releases'),
                _('Publish Android builds and update every device over the air.'),
                SettingsIcon.DEVICE,
                'releases:console',
                ('android', 'apk', 'app', 'release', 'update', 'ota', 'download', 'mobile', 'device'),
            ),
            SettingsItem(
                'file-storage',
                _('File storage'),
                _('Where media and backups are kept: this server or object storage.'),
                SettingsIcon.STORAGE,
                'accounts:file_storage',
                ('s3', 'object storage', 'bucket', 'r2', 'b2', 'wasabi', 'media', 'offsite'),
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
