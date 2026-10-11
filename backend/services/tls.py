"""TLS certificate management for the console.

The api container can read the certificates (``/etc/letsencrypt`` is mounted read-only) but never
writes them. Changes go through the shared runtime volume: the console writes ``cert-request.json``
(and, for an uploaded certificate, ``tls/incoming/``) and the certbot container acts on it and
reports back in ``cert-status.json``. The private key of an uploaded certificate is moved out of
the runtime volume by certbot as soon as it is installed.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

import dns.exception
import dns.resolver
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.x509.oid import ExtensionOID, NameOID

from backend.services.certificates import CertificateService
from backend.services.runtime import read_runtime_file, runtime_dir, write_runtime_file

logger = logging.getLogger('backend')

LETSENCRYPT_DIR = Path(os.environ.get('LETSENCRYPT_DIR', '/etc/letsencrypt'))
REQUEST_FILE = 'cert-request.json'
STATUS_FILE = 'cert-status.json'
MODE_FILE = 'tls-mode'
INCOMING = 'tls/incoming'
_WARN_DAYS, _ERR_DAYS = 30, 7
_PEM_CERT = re.compile(r'-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----', re.S)
_MAX_PEM = 64 * 1024


class TLSMode(StrEnum):
    LETSENCRYPT = 'letsencrypt'
    CUSTOM = 'custom'


class TLSAction(StrEnum):
    ISSUE = 'issue'  # (re)issue with the current hostname list
    RENEW = 'renew'  # force a renewal now
    CUSTOM = 'custom'  # install the uploaded certificate
    LETSENCRYPT = 'letsencrypt'  # leave the custom certificate, get a Let's Encrypt one


class CertificateError(ValueError):
    """An uploaded certificate or key is unusable (message is safe to show)."""


@dataclass(frozen=True)
class CertInfo:
    name: str
    subject: str
    issuer: str
    sans: tuple[str, ...]
    not_before: datetime
    not_after: datetime
    fingerprint: str
    self_signed: bool

    @property
    def days_left(self) -> int:
        return (self.not_after - datetime.now(UTC)).days

    @property
    def status(self) -> str:
        days = self.days_left
        return 'err' if days <= _ERR_DAYS else ('warn' if days <= _WARN_DAYS else 'ok')

    def covers(self, host: str) -> bool:
        host = host.lower()
        for san in self.sans:
            if san == host:
                return True
            if (
                san.startswith('*.')
                and host.count('.') == san.count('.')
                and host.endswith(san[1:])
            ):
                return True
        return False


@dataclass(frozen=True)
class HostCoverage:
    host: str
    covered: bool
    resolves_here: bool | None  # None when the lookup could not complete


@dataclass
class TLSStatus:
    mode: TLSMode
    active: CertInfo | None
    coverage: list[HostCoverage] = field(default_factory=list)
    last_request: dict[str, object] = field(default_factory=dict)
    pending: bool = False


def _name_text(name: x509.Name) -> str:
    attrs = name.get_attributes_for_oid(NameOID.COMMON_NAME)
    return attrs[0].value if attrs else name.rfc4514_string()


def parse_chain(pem: str) -> list[x509.Certificate]:
    if len(pem) > _MAX_PEM:
        raise CertificateError('That file is too large to be a certificate.')
    blocks = _PEM_CERT.findall(pem)
    if not blocks:
        raise CertificateError(
            'No certificate found: paste it in PEM form (-----BEGIN CERTIFICATE-----).'
        )
    try:
        return [x509.load_pem_x509_certificate(b.encode()) for b in blocks]
    except ValueError:
        raise CertificateError('The certificate could not be read.') from None


def describe(cert: x509.Certificate, name: str) -> CertInfo:
    try:
        sans = tuple(
            sorted(
                n.lower()
                for n in cert.extensions.get_extension_for_oid(
                    ExtensionOID.SUBJECT_ALTERNATIVE_NAME
                ).value.get_values_for_type(x509.DNSName)
            )
        )
    except x509.ExtensionNotFound:
        sans = ()
    return CertInfo(
        name=name,
        subject=_name_text(cert.subject),
        issuer=_name_text(cert.issuer),
        sans=sans or ((_name_text(cert.subject).lower(),)),
        not_before=cert.not_valid_before_utc,
        not_after=cert.not_valid_after_utc,
        fingerprint=cert.fingerprint(hashes.SHA256()).hex(),
        self_signed=cert.issuer == cert.subject,
    )


def validate_upload(cert_pem: str, key_pem: str, hostname: str) -> tuple[CertInfo, str, str]:
    """Check an uploaded certificate and key; returns (info, fullchain_pem, key_pem)."""
    chain = parse_chain(cert_pem)
    leaf = chain[0]
    if len(key_pem) > _MAX_PEM:
        raise CertificateError('That file is too large to be a private key.')
    try:
        key = serialization.load_pem_private_key(key_pem.encode(), password=None)
    except (ValueError, TypeError):
        raise CertificateError(
            'The private key could not be read. It must be in PEM form and not password protected.'
        ) from None
    public = serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    if key.public_key().public_bytes(*public) != leaf.public_key().public_bytes(*public):
        raise CertificateError('The private key does not belong to this certificate.')
    now = datetime.now(UTC)
    if leaf.not_valid_after_utc <= now:
        raise CertificateError('This certificate has expired.')
    if leaf.not_valid_before_utc > now:
        raise CertificateError('This certificate is not valid yet.')
    info = describe(leaf, 'custom')
    if hostname and not info.covers(hostname):
        raise CertificateError(
            f'This certificate does not cover the mail hostname {hostname} '
            f'(it covers: {", ".join(info.sans) or "nothing"}).'
        )
    fullchain = ''.join(c.public_bytes(serialization.Encoding.PEM).decode() for c in chain)
    return info, fullchain, key_pem.strip() + '\n'


def _public_resolver() -> dns.resolver.Resolver:
    raw = os.environ.get('DELIVERABILITY_DNS_RESOLVERS', '')
    servers = [r.strip() for r in raw.split(',') if r.strip()] or ['1.1.1.1', '8.8.8.8']
    resolver = dns.resolver.Resolver(configure=False)
    resolver.nameservers = servers
    port = os.environ.get('DELIVERABILITY_DNS_PORT', '')
    if port.isdigit():
        resolver.port = int(port)
    resolver.lifetime, resolver.timeout = 5.0, 3.0
    return resolver


class TLSService:
    @staticmethod
    def mode() -> TLSMode:
        text = (read_runtime_file(MODE_FILE) or '').strip()
        return TLSMode.CUSTOM if text == 'custom' else TLSMode.LETSENCRYPT

    @staticmethod
    def active_certificate() -> CertInfo | None:
        host = CertificateService.mail_hostname()
        path = LETSENCRYPT_DIR / 'live' / host / 'fullchain.pem'
        try:
            return describe(parse_chain(path.read_text())[0], host)
        except (OSError, CertificateError):
            return None

    @staticmethod
    def coverage(domain_names: list[str], cert: CertInfo | None) -> list[HostCoverage]:
        resolver = _public_resolver()
        here = os.environ.get('SERVER_IP', '').strip()
        rows = []
        for host in CertificateService.hosts_for(domain_names):
            resolves: bool | None
            try:
                answers = {r.to_text() for r in resolver.resolve(host, 'A')}
                resolves = (here in answers) if here else bool(answers)
            except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
                resolves = False
            except (dns.exception.DNSException, OSError):
                resolves = None
            rows.append(HostCoverage(host, bool(cert and cert.covers(host)), resolves))
        return rows

    @staticmethod
    def last_status() -> dict[str, object]:
        try:
            data = json.loads(read_runtime_file(STATUS_FILE) or '{}')
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def pending_request() -> dict[str, object] | None:
        try:
            request = json.loads(read_runtime_file(REQUEST_FILE) or 'null')
        except ValueError:
            return None
        return request if isinstance(request, dict) else None

    @staticmethod
    def status(domain_names: list[str], *, with_coverage: bool = True) -> TLSStatus:
        cert = TLSService.active_certificate()
        last = TLSService.last_status()
        request = TLSService.pending_request()
        pending = bool(request and request.get('id') != last.get('request_id'))
        return TLSStatus(
            mode=TLSService.mode(),
            active=cert,
            coverage=TLSService.coverage(domain_names, cert) if with_coverage else [],
            last_request=last,
            pending=pending,
        )

    @staticmethod
    def request(action: TLSAction) -> str:
        """Ask the certbot container to do ``action``; returns the request id."""
        request_id = uuid.uuid4().hex
        payload = {'id': request_id, 'action': action.value, 'at': datetime.now(UTC).isoformat()}
        write_runtime_file(REQUEST_FILE, json.dumps(payload))
        return request_id

    @staticmethod
    def install_custom(cert_pem: str, key_pem: str) -> CertInfo:
        """Validate an uploaded certificate and hand it to certbot to install."""
        info, fullchain, key = validate_upload(
            cert_pem, key_pem, CertificateService.mail_hostname()
        )
        write_runtime_file(f'{INCOMING}/fullchain.pem', fullchain, mode=0o644)
        write_runtime_file(f'{INCOMING}/privkey.pem', key, mode=0o600)
        TLSService.request(TLSAction.CUSTOM)
        return info

    @staticmethod
    def clear_incoming() -> None:
        for name in ('fullchain.pem', 'privkey.pem'):
            (runtime_dir() / INCOMING / name).unlink(missing_ok=True)
