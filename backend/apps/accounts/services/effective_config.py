"""Read-only views of the effective server configuration.

Values come from Django settings and the deployment environment. Secrets are
never returned: a secret row only reports whether it is configured.
"""

from __future__ import annotations

import os
import platform
from datetime import datetime

import django
from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext as _

from ..types.settings import ConfigRow, ConfigSection


def _env(name: str, default: str = '') -> str:
    return os.environ.get(name, default).strip()


def _flag(value: object) -> str:
    return str(_('Enabled')) if value else str(_('Disabled'))


def _tone(value: object) -> str:
    return 'success' if value else 'warning'


def _secret(name: str, *, label: str) -> ConfigRow:
    configured = bool(_env(name))
    return ConfigRow(
        label=label,
        value=str(_('Configured')) if configured else str(_('Not set')),
        env=name,
        tone='success' if configured else '',
    )


def _unset(value: str) -> str:
    return value or str(_('Not set'))


def _mail_domain() -> str:
    return _env('DOMAIN') or _env('MAIL_DOMAIN')


class EffectiveConfig:
    """Builders, one per settings page, returning typed read-only sections."""

    @staticmethod
    def mail() -> list[ConfigSection]:
        domain = _mail_domain()
        hostname = _env('MAIL_HOSTNAME') or (f'mail.{domain}' if domain else '')
        return [
            ConfigSection(
                str(_('Identity')),
                (
                    ConfigRow(str(_('Mail domain')), _unset(domain), 'DOMAIN', mono=True),
                    ConfigRow(
                        str(_('Mail hostname')), _unset(hostname), 'MAIL_HOSTNAME', mono=True
                    ),
                    ConfigRow(
                        str(_('Default sender')),
                        str(settings.DEFAULT_FROM_EMAIL),
                        'DEFAULT_FROM_EMAIL',
                        mono=True,
                    ),
                ),
            ),
            ConfigSection(
                str(_('Relay')),
                (
                    ConfigRow(
                        str(_('Smart host')),
                        _unset(_env('MAIL_SMART_HOST')),
                        'MAIL_SMART_HOST',
                        mono=True,
                    ),
                    ConfigRow(
                        str(_('SMTP proxy')),
                        _unset(_env('MAIL_SMTP_PROXY')),
                        'MAIL_SMTP_PROXY',
                        mono=True,
                    ),
                    ConfigRow(
                        str(_('Maximum hops')),
                        _env('MAIL_MAX_HOP_COUNT', '30'),
                        'MAIL_MAX_HOP_COUNT',
                    ),
                ),
            ),
            ConfigSection(
                str(_('Application mail transport')),
                (
                    ConfigRow(
                        str(_('Backend')),
                        str(settings.EMAIL_BACKEND).rsplit('.', 2)[-2],
                        'EMAIL_BACKEND',
                    ),
                    ConfigRow(
                        str(_('Host')),
                        f'{settings.EMAIL_HOST}:{settings.EMAIL_PORT}',
                        'EMAIL_HOST',
                        mono=True,
                    ),
                    ConfigRow(
                        str(_('Username')),
                        _unset(str(settings.EMAIL_HOST_USER)),
                        'EMAIL_HOST_USER',
                        mono=True,
                    ),
                    _secret('EMAIL_HOST_PASSWORD', label=str(_('Password'))),
                    ConfigRow(
                        str(_('STARTTLS')),
                        _flag(settings.EMAIL_USE_TLS),
                        'EMAIL_USE_TLS',
                        tone=_tone(settings.EMAIL_USE_TLS),
                    ),
                    ConfigRow(
                        str(_('Implicit TLS')), _flag(settings.EMAIL_USE_SSL), 'EMAIL_USE_SSL'
                    ),
                ),
                str(
                    _(
                        'How the admin console itself sends mail such as '
                        'verification and reset messages.'
                    )
                ),
            ),
        ]

    @staticmethod
    def deliverability() -> list[ConfigSection]:
        from backend.services.deliverability import DeliverabilityService

        resolvers = DeliverabilityService.resolvers()
        rbls = DeliverabilityService.blocklists()
        return [
            ConfigSection(
                str(_('Signing & policy')),
                (
                    ConfigRow(
                        str(_('DKIM selector')),
                        _env('DKIM_SELECTOR', 'default'),
                        'DKIM_SELECTOR',
                        mono=True,
                    ),
                    ConfigRow(
                        str(_('DKIM key directory')),
                        _unset(_env('DKIM_KEY_DIR')),
                        'DKIM_KEY_DIR',
                        mono=True,
                    ),
                    ConfigRow(
                        str(_('MTA-STS policy id')),
                        _unset(_env('MTA_STS_ID')),
                        'MTA_STS_ID',
                        mono=True,
                    ),
                    ConfigRow(str(_('DNS record TTL')), _env('DNS_TTL', '3600') + ' s', 'DNS_TTL'),
                ),
            ),
            ConfigSection(
                str(_('Checks')),
                (
                    ConfigRow(
                        str(_('SMTP port probe')), _env('SMTP_PORT_CHECK', '25'), 'SMTP_PORT_CHECK'
                    ),
                    ConfigRow(
                        str(_('DNS resolvers')),
                        ', '.join(resolvers),
                        'DELIVERABILITY_DNS_RESOLVERS',
                        mono=True,
                    ),
                    ConfigRow(
                        str(_('Blocklists')), ', '.join(rbls), 'DELIVERABILITY_RBLS', mono=True
                    ),
                ),
                str(_('Resolvers and blocklists queried when the dashboard runs a rescan.')),
            ),
        ]

    @staticmethod
    def security() -> list[ConfigSection]:
        secure = not settings.DEBUG
        return [
            ConfigSection(
                str(_('Sign-in protection')),
                (
                    ConfigRow(
                        str(_('Failed attempts before lockout')),
                        str(getattr(settings, 'AXES_FAILURE_LIMIT', '—')),
                        'AXES_FAILURE_LIMIT',
                    ),
                    ConfigRow(
                        str(_('Lockout cool-off')),
                        f'{getattr(settings, "AXES_COOLOFF_TIME", "—")} h',
                        'AXES_COOLOFF_TIME',
                    ),
                    ConfigRow(
                        str(_('Password rules')),
                        str(len(settings.AUTH_PASSWORD_VALIDATORS))
                        + ' '
                        + str(_('validators active')),
                    ),
                ),
            ),
            ConfigSection(
                str(_('Cookies & transport')),
                (
                    ConfigRow(
                        str(_('HTTPS redirect')),
                        _flag(getattr(settings, 'SECURE_SSL_REDIRECT', False)),
                        'SECURE_SSL_REDIRECT',
                        tone=_tone(getattr(settings, 'SECURE_SSL_REDIRECT', False) or not secure),
                    ),
                    ConfigRow(
                        str(_('HSTS')),
                        f'{getattr(settings, "SECURE_HSTS_SECONDS", 0)} s',
                        'SECURE_HSTS_SECONDS',
                    ),
                    ConfigRow(
                        str(_('Secure session cookie')),
                        _flag(getattr(settings, 'SESSION_COOKIE_SECURE', False)),
                        'SESSION_COOKIE_SECURE',
                    ),
                    ConfigRow(
                        str(_('Secure CSRF cookie')),
                        _flag(getattr(settings, 'CSRF_COOKIE_SECURE', False)),
                        'CSRF_COOKIE_SECURE',
                    ),
                    ConfigRow(
                        str(_('Referrer policy')),
                        str(getattr(settings, 'SECURE_REFERRER_POLICY', '—')),
                        'SECURE_REFERRER_POLICY',
                        mono=True,
                    ),
                ),
            ),
            ConfigSection(
                str(_('Content security policy')),
                (
                    ConfigRow(
                        str(_('Mode')),
                        str(_('Report only'))
                        if getattr(settings, 'CSP_REPORT_ONLY', False)
                        else str(_('Enforced')),
                        'CSP_REPORT_ONLY',
                        tone='' if getattr(settings, 'CSP_REPORT_ONLY', False) else 'success',
                    ),
                    ConfigRow(
                        str(_('Report endpoint')),
                        str(getattr(settings, 'CSP_REPORT_URI', '—')),
                        'CSP_REPORT_URI',
                        mono=True,
                    ),
                ),
                str(
                    _(
                        'Inline scripts are never permitted; the console ships all scripts '
                        'from its own origin.'
                    )
                ),
            ),
        ]

    @staticmethod
    def monitoring() -> list[ConfigSection]:
        return [
            ConfigSection(
                str(_('Log levels')),
                (
                    ConfigRow(
                        str(_('Application')),
                        _env('LOG_LEVEL_BACKEND', 'INFO'),
                        'LOG_LEVEL_BACKEND',
                        mono=True,
                    ),
                    ConfigRow(
                        str(_('Django')),
                        _env('LOG_LEVEL_DJANGO', 'WARNING'),
                        'LOG_LEVEL_DJANGO',
                        mono=True,
                    ),
                    ConfigRow(
                        str(_('Requests')),
                        _env('LOG_LEVEL_DJANGO_REQUEST', 'WARNING'),
                        'LOG_LEVEL_DJANGO_REQUEST',
                        mono=True,
                    ),
                    ConfigRow(
                        str(_('Security')),
                        _env('LOG_LEVEL_DJANGO_SECURITY', 'WARNING'),
                        'LOG_LEVEL_DJANGO_SECURITY',
                        mono=True,
                    ),
                    ConfigRow(
                        str(_('Root')),
                        _env('LOG_LEVEL_ROOT', 'WARNING'),
                        'LOG_LEVEL_ROOT',
                        mono=True,
                    ),
                ),
            ),
            ConfigSection(
                str(_('Error reporting')),
                (
                    _secret('SENTRY_DSN', label=str(_('Sentry'))),
                    ConfigRow(
                        str(_('Environment')),
                        _env('SENTRY_ENVIRONMENT', 'production'),
                        'SENTRY_ENVIRONMENT',
                    ),
                    ConfigRow(
                        str(_('Trace sample rate')),
                        _env('SENTRY_TRACES_RATE', '0.1'),
                        'SENTRY_TRACES_RATE',
                    ),
                ),
            ),
        ]

    @staticmethod
    def storage() -> list[ConfigSection]:
        return [
            ConfigSection(
                str(_('Locations')),
                (
                    ConfigRow(
                        str(_('Mail store')),
                        _env('MAIL_VHOSTS_DIR', '/var/mail/vhosts'),
                        'MAIL_VHOSTS_DIR',
                        mono=True,
                    ),
                    ConfigRow(
                        str(_('Uploaded media')), str(settings.MEDIA_ROOT), 'MEDIA_ROOT', mono=True
                    ),
                    ConfigRow(
                        str(_('Static files')), str(settings.STATIC_ROOT), 'STATIC_ROOT', mono=True
                    ),
                    ConfigRow(
                        str(_('Disk checks')),
                        _env('DISK_CHECK_PATHS') or str(_('Mail store, app directory and /')),
                        'DISK_CHECK_PATHS',
                        mono=True,
                    ),
                ),
            ),
            ConfigSection(
                str(_('Certificates')),
                (
                    ConfigRow(
                        str(_('Let’s Encrypt directory')),
                        _env('LETSENCRYPT_DIR', '/etc/letsencrypt'),
                        'LETSENCRYPT_DIR',
                        mono=True,
                    ),
                ),
                str(
                    _(
                        'Certificate expiry is monitored from here; see the dashboard '
                        'for the current status.'
                    )
                ),
            ),
        ]

    @staticmethod
    def language() -> list[ConfigSection]:
        now: datetime = timezone.localtime() if settings.USE_TZ else datetime.now()
        return [
            ConfigSection(
                str(_('Locale')),
                (
                    ConfigRow(
                        str(_('Interface language')),
                        str(settings.LANGUAGE_CODE),
                        'LANGUAGE_CODE',
                        mono=True,
                    ),
                    ConfigRow(str(_('Time zone')), str(settings.TIME_ZONE), 'TIME_ZONE', mono=True),
                    ConfigRow(str(_('Server time')), now.strftime('%Y-%m-%d %H:%M:%S %Z').strip()),
                ),
            ),
        ]

    @staticmethod
    def about() -> list[ConfigSection]:
        return [
            ConfigSection(
                str(_('This server')),
                (
                    ConfigRow(
                        str(_('Version')),
                        _env('APP_VERSION', 'v2.4.0-stable'),
                        'APP_VERSION',
                        mono=True,
                    ),
                    ConfigRow(str(_('Framework')), f'Django {django.get_version()}', mono=True),
                    ConfigRow(str(_('Python')), platform.python_version(), mono=True),
                    ConfigRow(
                        str(_('Environment')),
                        str(_('Development')) if settings.DEBUG else str(_('Production')),
                    ),
                ),
            ),
        ]
