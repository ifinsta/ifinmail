"""Settings of the authoritative DNS server (the ``dns`` container, Knot DNS)."""

from __future__ import annotations

import ipaddress
import os

from django.core.cache import cache

from backend.apps.core.services import SystemSettings
from backend.apps.core.types import SettingKey

_IP_CACHE_KEY = 'dns-server-ip'
_IP_CACHE_SECONDS = 3600
# The dns container mounts the runtime volume here; the app writes the same files
# under IFINMAIL_RUNTIME_DIR, so the generated Knot configuration uses this path.
DEFAULT_CONTAINER_RUNTIME = '/runtime'


class DNSServerConfig:
    @staticmethod
    def enabled() -> bool:
        return os.environ.get('DNS_SERVER_ENABLED', '1').strip().lower() not in ('0', 'false', 'no')

    @staticmethod
    def dav_enabled() -> bool:
        """Calendars and contacts (the optional ``dav`` container, DAV_ENABLED)."""
        return os.environ.get('DAV_ENABLED', '1').strip().lower() not in ('0', 'false', 'no')

    @staticmethod
    def container_runtime() -> str:
        return os.environ.get('DNS_CONTAINER_RUNTIME', DEFAULT_CONTAINER_RUNTIME).rstrip('/')

    @staticmethod
    def query_host() -> str:
        """Where the app reaches the dns container to prove it answers."""
        return os.environ.get('DNS_SERVER_HOST', 'dns')

    @staticmethod
    def query_port() -> int:
        raw = os.environ.get('DNS_SERVER_PORT', '53')
        return int(raw) if raw.isdigit() else 53

    @staticmethod
    def mail_hostname() -> str:
        return os.environ.get('MAIL_HOSTNAME', '').strip().lower().rstrip('.')

    @staticmethod
    def ns_hosts() -> list[str]:
        """Names of this server's nameservers (``DNS_NS_HOSTS`` or ns1/ns2 under the mail host)."""
        raw = os.environ.get('DNS_NS_HOSTS', '')
        hosts = [h.strip().lower().rstrip('.') for h in raw.split(',') if h.strip()]
        if hosts:
            return hosts
        base = DNSServerConfig.mail_hostname()
        return [f'ns1.{base}', f'ns2.{base}'] if base else []

    @staticmethod
    def server_ipv4() -> str:
        """Public IPv4: ``SERVER_IP`` if set, otherwise detected once an hour."""
        configured = os.environ.get('SERVER_IP', '').strip()
        if configured:
            return configured
        cached = cache.get(_IP_CACHE_KEY)
        if cached:
            return cached
        from .. import services as dns_services  # late: DNSService imports models

        ip = dns_services.DNSService.get_server_ip()
        if ip and ip != '0.0.0.0':
            cache.set(_IP_CACHE_KEY, ip, _IP_CACHE_SECONDS)
        return ip

    @staticmethod
    def server_ipv6() -> str:
        value = os.environ.get('SERVER_IPV6', '').strip()
        try:
            return str(ipaddress.IPv6Address(value)) if value else ''
        except ValueError:
            return ''

    @staticmethod
    def hostmaster(zone: str) -> str:
        return f'hostmaster.{zone}'

    @staticmethod
    def secondaries() -> list[str]:
        """IP addresses of secondary nameservers that may transfer our zones."""
        raw = SystemSettings.get(SettingKey.DNS_SECONDARIES, [])
        return [str(ip) for ip in raw] if isinstance(raw, list) else []

    @staticmethod
    def set_secondaries(addresses: list[str]) -> list[str]:
        clean: list[str] = []
        for raw in addresses:
            text = raw.strip()
            if not text:
                continue
            try:
                clean.append(str(ipaddress.ip_address(text)))
            except ValueError as exc:
                raise ValueError(f'{text!r} is not an IP address') from exc
        SystemSettings.set(SettingKey.DNS_SECONDARIES, sorted(set(clean)))
        return DNSServerConfig.secondaries()

    @staticmethod
    def caa_enabled() -> bool:
        return SystemSettings.get_bool(SettingKey.DNS_CAA_ENABLED, True)
