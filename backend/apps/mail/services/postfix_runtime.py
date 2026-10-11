"""Outbound mail settings edited in the console and applied to Postfix.

The console stores the choices in SystemSettings and renders them to
``postfix-overrides.conf`` on the shared runtime volume. A small watcher inside
the postfix container (provisioning/docker/postfix/sync-overrides.sh) applies
the file with ``postconf`` and reloads Postfix within seconds, so a toggle in the
UI really changes how mail is sent.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from backend.apps.core.platform.services.runtime import write_runtime_file
from backend.apps.core.services import SystemSettings
from backend.apps.core.types import SettingKey

OVERRIDES_FILE = 'postfix-overrides.conf'
MIN_HOPS, MAX_HOPS, DEFAULT_HOPS = 5, 30, 10
_TRUE_WORDS = ('1', 'true', 'yes', 'on')
_FALSE_WORDS = ('', '0', 'false', 'no', 'off')


class OutboundConfigError(ValueError):
    pass


def _env_host(name: str) -> str:
    """Hostname held in an env var, ignoring legacy boolean-style values."""
    value = os.environ.get(name, '').strip()
    return '' if value.lower() in _TRUE_WORDS + _FALSE_WORDS else value


def _env_enabled(name: str) -> bool:
    value = os.environ.get(name, '').strip().lower()
    return value in _TRUE_WORDS or bool(_env_host(name))


def _with_port(host: str, default_port: int) -> str:
    """Postfix syntax for a host that must not be MX-resolved: ``[host]:port``."""
    name, sep, port = host.rpartition(':')
    if sep and port.isdigit():
        return f'[{name}]:{port}'
    return f'[{host}]:{default_port}'


@dataclass(frozen=True)
class OutboundState:
    smart_host_enabled: bool
    smart_host: str
    smtp_proxy_enabled: bool
    smtp_proxy: str
    max_hops: int


class PostfixRuntime:
    @staticmethod
    def state() -> OutboundState:
        return OutboundState(
            smart_host_enabled=SystemSettings.get_bool(
                SettingKey.SMART_HOST_ENABLED, _env_enabled('MAIL_SMART_HOST')
            ),
            smart_host=_env_host('MAIL_SMART_HOST'),
            smtp_proxy_enabled=SystemSettings.get_bool(
                SettingKey.SMTP_PROXY_ENABLED, _env_enabled('MAIL_SMTP_PROXY')
            ),
            smtp_proxy=_env_host('MAIL_SMTP_PROXY'),
            max_hops=SystemSettings.get_int(
                SettingKey.MAX_HOPS,
                int(os.environ.get('MAIL_MAX_HOP_COUNT', DEFAULT_HOPS) or DEFAULT_HOPS),
            ),
        )

    @staticmethod
    def render(state: OutboundState | None = None) -> str:
        """Postfix ``key = value`` lines for the current state (empty value = reset to default)."""
        state = state or PostfixRuntime.state()
        relayhost = ''
        if state.smart_host_enabled and state.smart_host:
            relayhost = _with_port(state.smart_host, 587)
        default_transport = ''
        if state.smtp_proxy_enabled and state.smtp_proxy:
            default_transport = f'smtp:{_with_port(state.smtp_proxy, 25)}'
        hops = max(MIN_HOPS, min(MAX_HOPS, state.max_hops))
        return (
            f'relayhost = {relayhost}\n'
            f'default_transport = {default_transport}\n'
            f'hopcount_limit = {hops}\n'
        )

    @staticmethod
    def apply() -> str:
        """Render and publish the overrides; returns the text written."""
        text = PostfixRuntime.render()
        write_runtime_file(OVERRIDES_FILE, text)
        return text

    @staticmethod
    def set_smart_host(enabled: bool) -> OutboundState:
        if enabled and not _env_host('MAIL_SMART_HOST'):
            raise OutboundConfigError(
                'Set MAIL_SMART_HOST to the relay hostname in the server environment first.'
            )
        SystemSettings.set(SettingKey.SMART_HOST_ENABLED, enabled)
        PostfixRuntime.apply()
        return PostfixRuntime.state()

    @staticmethod
    def set_smtp_proxy(enabled: bool) -> OutboundState:
        if enabled and not _env_host('MAIL_SMTP_PROXY'):
            raise OutboundConfigError(
                'Set MAIL_SMTP_PROXY to the proxy hostname in the server environment first.'
            )
        SystemSettings.set(SettingKey.SMTP_PROXY_ENABLED, enabled)
        PostfixRuntime.apply()
        return PostfixRuntime.state()

    @staticmethod
    def set_max_hops(value: int) -> OutboundState:
        if not MIN_HOPS <= value <= MAX_HOPS:
            raise OutboundConfigError(f'Hop count must be between {MIN_HOPS} and {MAX_HOPS}.')
        SystemSettings.set(SettingKey.MAX_HOPS, value)
        PostfixRuntime.apply()
        return PostfixRuntime.state()
