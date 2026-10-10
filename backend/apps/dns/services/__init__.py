"""DNS provider service layer."""

import base64
import hashlib
import json
import logging
import os
import socket

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core import signing
from django.db.utils import OperationalError

from ..models import DNSProviderConfig
from ..providers.base import DNSRecord
from ..providers.cloudflare import CloudflareProvider
from ..providers.digitalocean import DigitalOceanProvider
from ..providers.porkbun import PorkbunProvider

logger = logging.getLogger('backend')

PROVIDER_MAP = {
    'cloudflare': (CloudflareProvider, {'api_token'}, 'API Token'),
    'porkbun': (PorkbunProvider, {'api_key', 'secret_key'}, 'API Key + Secret Key'),
    'digitalocean': (DigitalOceanProvider, {'api_token'}, 'API Token'),
}

_IPIFY_URL = 'https://api.ipify.org'
_DEFAULT_DNS_TTL = int(os.environ.get('DNS_TTL', '3600'))
_DKIM_KEY_DIR = os.environ.get('DKIM_KEY_DIR', '/etc/dkim')
_CRED_PREFIX = 'fernet:'
DKIM_PLACEHOLDER = '<add-dkim-key>'


def _fernet() -> Fernet:
    """Cipher for stored provider credentials, derived from the Django secret key."""
    seed = f'dns-credentials:{settings.SECRET_KEY}'.encode()
    key = base64.urlsafe_b64encode(hashlib.sha256(seed).digest())
    return Fernet(key)


def encrypt_credentials(credentials: dict) -> str:
    return _CRED_PREFIX + _fernet().encrypt(json.dumps(credentials).encode()).decode()


def decrypt_credentials(stored: object) -> dict:
    """Read credentials stored encrypted, or in the older signed/plain formats."""
    if isinstance(stored, str) and stored.startswith(_CRED_PREFIX):
        try:
            return json.loads(_fernet().decrypt(stored[len(_CRED_PREFIX) :].encode()))
        except (InvalidToken, ValueError) as exc:
            raise ValueError('Stored DNS credentials cannot be decrypted') from exc
    try:
        return signing.loads(stored)  # legacy: signed but readable
    except (signing.BadSignature, TypeError):
        if isinstance(stored, dict):
            return stored
        raise ValueError('Stored DNS credentials are unreadable') from None


class DNSService:
    @staticmethod
    def get_first_config() -> DNSProviderConfig | None:
        return DNSProviderConfig.objects.first()

    @staticmethod
    def get_config_by_provider(provider_name: str) -> DNSProviderConfig | None:
        try:
            return DNSProviderConfig.objects.filter(provider=provider_name).first()
        except OperationalError:
            return None

    @staticmethod
    def update_or_create_config(
        provider_name: str,
        credentials: dict,
    ) -> tuple[DNSProviderConfig, bool]:
        # Encrypt before the DB write: the table holds API tokens that can edit DNS.
        config, created = DNSProviderConfig.objects.update_or_create(
            provider=provider_name,
            defaults={'credentials': encrypt_credentials(credentials)},
        )
        # Return the usable in-memory shape while keeping the stored value signed.
        config.credentials = credentials
        return config, created

    @staticmethod
    def get_server_ip() -> str:
        """Auto-detect the server's public IPv4 address."""
        ip_check_url = os.environ.get('IP_CHECK_URL', _IPIFY_URL)
        try:
            import requests as req

            resp = req.get(ip_check_url, timeout=5)
            if resp.status_code == 200:
                ip = resp.text.strip()
                if ip.startswith('10.') or ip.startswith('192.168.') or ip.startswith('127.'):
                    logger.warning(
                        'Detected private IP %s via ipify, trying MAIL_HOSTNAME fallback',
                        ip,
                    )
                elif ip.startswith('172.'):
                    parts = ip.split('.')
                    if len(parts) == 4 and 16 <= int(parts[1]) <= 31:
                        logger.warning(
                            'Detected private IP %s via ipify, trying MAIL_HOSTNAME fallback',
                            ip,
                        )
                    else:
                        return ip
                else:
                    return ip
        except Exception:
            logger.exception('Failed to detect public IP via %s', ip_check_url)
        mail_hostname = os.environ.get('MAIL_HOSTNAME')
        if mail_hostname:
            try:
                resolved = socket.gethostbyname(mail_hostname)
                logger.info('Resolved MAIL_HOSTNAME %s to %s as fallback', mail_hostname, resolved)
                return resolved
            except Exception:
                logger.exception('Failed to resolve MAIL_HOSTNAME %s', mail_hostname)
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return '0.0.0.0'

    @staticmethod
    def get_provider(
        provider_name: str,
    ) -> CloudflareProvider | DigitalOceanProvider | PorkbunProvider | None:
        config = DNSService.get_config_by_provider(provider_name)
        if not config:
            return None
        cls, _, _ = PROVIDER_MAP[provider_name]
        try:
            decrypted = decrypt_credentials(config.credentials)
        except ValueError:
            logger.exception('Cannot read stored credentials for %s', provider_name)
            return None
        return cls(**decrypted)

    @staticmethod
    def _dkim_public_value(domain: str, selector: str) -> str:
        """Published DKIM value: database key first, then a key file from older installs."""
        try:
            from backend.apps.domains.services.dkim import DKIMService

            value = DKIMService.txt_value_for(domain, selector)
            if value:
                return value
        except Exception:  # database unavailable (e.g. before migrations): fall back to files
            logger.debug('DKIM lookup in the database failed for %s', domain, exc_info=True)
        for name in (f'{domain}.{selector}.pub', f'{selector}.{domain}.pub'):
            path = os.path.join(_DKIM_KEY_DIR, name)
            if os.path.isfile(path):
                try:
                    with open(path) as handle:
                        body = ''.join(line.strip() for line in handle if not line.startswith('-'))
                except OSError:
                    continue
                if body:
                    return f'v=DKIM1; k=rsa; p={body}'
        return ''

    @staticmethod
    def has_placeholder(records: list[DNSRecord]) -> bool:
        return any(DKIM_PLACEHOLDER in r.value for r in records)

    @staticmethod
    def build_records(
        domain: str,
        server_ip: str,
        ip_address: str | None = None,
    ) -> list[DNSRecord]:
        resolved_ip = ip_address or server_ip
        mail_hostname = os.environ.get('MAIL_HOSTNAME', f'mail.{domain}')
        dkim_selector = os.environ.get('DKIM_SELECTOR', 'default')
        dmarc_policy = os.environ.get('DMARC_POLICY', 'quarantine')
        ttl = _DEFAULT_DNS_TTL

        dkim_txt_value = DNSService._dkim_public_value(domain, dkim_selector) or (
            f'v=DKIM1; k=rsa; p={DKIM_PLACEHOLDER}'
        )

        # The id changes whenever the policy mode changes so receivers re-fetch it.
        mta_sts_mode = os.environ.get('MTA_STS_MODE', 'testing')
        mta_sts_id = (
            os.environ.get('MTA_STS_ID')
            or hashlib.sha256(
                f'mta-sts:{domain}:{mail_hostname}:{mta_sts_mode}'.encode()
            ).hexdigest()[:16]
        )

        return [
            DNSRecord(type='A', name='@', value=resolved_ip, ttl=ttl),
            DNSRecord(type='A', name='mail', value=resolved_ip, ttl=ttl),
            DNSRecord(type='A', name='mta-sts', value=resolved_ip, ttl=ttl),
            DNSRecord(type='CNAME', name='autoconfig', value=mail_hostname, ttl=ttl),
            DNSRecord(type='CNAME', name='autodiscover', value=mail_hostname, ttl=ttl),
            DNSRecord(type='MX', name='@', value=mail_hostname, priority=10, ttl=ttl),
            DNSRecord(type='TXT', name='@', value='v=spf1 mx -all', ttl=ttl),
            DNSRecord(
                type='TXT',
                name='_dmarc',
                value=f'v=DMARC1; p={dmarc_policy}; rua=mailto:postmaster@{domain}',
                ttl=ttl,
            ),
            DNSRecord(type='TXT', name='_mta-sts', value=f'v=STSv1; id={mta_sts_id}', ttl=ttl),
            DNSRecord(
                type='TXT',
                name=f'{dkim_selector}._domainkey',
                value=dkim_txt_value,
                ttl=ttl,
            ),
        ]
