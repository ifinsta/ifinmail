"""DNS verification: checks the records a domain needs and records the outcome.

Rules that protect mail flow:
* A lookup that *errors* (timeout, SERVFAIL) never changes stored state.
* ``Domain.verified`` (which Postfix uses to accept mail) is only ever switched
  *on* automatically, when MX points at this server. It is never switched off
  here, so a DNS hiccup cannot make the server start rejecting mail.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import dns.exception
import dns.resolver
from django.utils import timezone

from backend.apps.core.services import SystemSettings
from backend.apps.core.types import SettingKey

from ..models import Domain
from ..types.provisioning import CheckStatus, DNSCheck, VerificationResult
from .dkim import DKIMService, default_selector

logger = logging.getLogger('backend')

_DEFAULT_RESOLVERS = ('1.1.1.1', '8.8.8.8', '9.9.9.9')


def _resolver() -> dns.resolver.Resolver:
    """A resolver that talks to public DNS directly, bypassing local caches."""
    raw = os.environ.get('DELIVERABILITY_DNS_RESOLVERS', '')
    servers = [r.strip() for r in raw.split(',') if r.strip()] or list(_DEFAULT_RESOLVERS)
    resolver = dns.resolver.Resolver(configure=False)
    resolver.nameservers = servers
    port = os.environ.get('DELIVERABILITY_DNS_PORT', '')
    if port.isdigit():  # lets a lab or test run point at a local DNS server
        resolver.port = int(port)
    resolver.lifetime = 6.0
    resolver.timeout = 3.0
    return resolver


def _lookup(name: str, rdtype: str) -> list[str] | None:
    """Return record strings, ``[]`` for a clean "no such record", ``None`` on lookup failure."""
    try:
        answer = _resolver().resolve(name, rdtype)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return []
    except (dns.exception.DNSException, OSError) as exc:
        logger.warning('DNS %s lookup for %s failed: %s', rdtype, name, exc)
        return None
    values: list[str] = []
    for rdata in answer:
        if rdtype == 'TXT':
            values.append(b''.join(rdata.strings).decode('utf-8', errors='replace'))
        elif rdtype == 'MX':
            values.append(f'{rdata.preference} {str(rdata.exchange).rstrip(".").lower()}')
        else:
            values.append(rdata.to_text())
    return values


def _norm(host: str) -> str:
    return host.strip().rstrip('.').lower()


def _compact(value: str) -> str:
    return ''.join(value.split()).strip('"')


class DomainVerificationService:
    @staticmethod
    def mail_hostname(domain: str) -> str:
        return _norm(os.environ.get('MAIL_HOSTNAME', f'mail.{domain}'))

    @staticmethod
    def check_mx(domain: str) -> DNSCheck:
        records = _lookup(domain, 'MX')
        if records is None:
            return DNSCheck(CheckStatus.ERROR, 'MX lookup failed')
        if not records:
            return DNSCheck(CheckStatus.FAIL, 'No MX record found')
        wanted = DomainVerificationService.mail_hostname(domain)
        hosts = [r.split(' ', 1)[1] for r in records]
        if wanted in hosts:
            return DNSCheck(CheckStatus.PASS, f'MX points at {wanted}')
        return DNSCheck(CheckStatus.FAIL, f'MX points at {", ".join(hosts)}, expected {wanted}')

    @staticmethod
    def check_spf(domain: str) -> DNSCheck:
        records = _lookup(domain, 'TXT')
        if records is None:
            return DNSCheck(CheckStatus.ERROR, 'TXT lookup failed')
        spf = [r for r in records if r.lower().startswith('v=spf1')]
        if not spf:
            return DNSCheck(CheckStatus.FAIL, 'No SPF record found')
        if len(spf) > 1:
            return DNSCheck(CheckStatus.FAIL, 'More than one SPF record (invalid)')
        terms = spf[0].lower().split()
        if any(t in ('mx', '+mx', 'a', '+a') or t.startswith(('ip4:', 'include:')) for t in terms):
            return DNSCheck(CheckStatus.PASS, 'SPF record found')
        return DNSCheck(CheckStatus.FAIL, 'SPF record does not authorise this server')

    @staticmethod
    def check_dkim(domain: str) -> DNSCheck:
        selector = default_selector()
        expected = DKIMService.txt_value_for(domain, selector)
        if not expected:
            return DNSCheck(CheckStatus.FAIL, 'No DKIM key generated for this domain')
        records = _lookup(f'{selector}._domainkey.{domain}', 'TXT')
        if records is None:
            return DNSCheck(CheckStatus.ERROR, 'DKIM lookup failed')
        if not records:
            return DNSCheck(CheckStatus.FAIL, 'No DKIM record found')
        want = _compact(expected).split('p=', 1)[1]
        for record in records:
            if 'v=dkim1' in record.lower() and want == _compact(record).split('p=', 1)[-1]:
                return DNSCheck(CheckStatus.PASS, 'DKIM record matches the server key')
        return DNSCheck(CheckStatus.FAIL, 'DKIM record does not match the server key')

    @staticmethod
    def check_dmarc(domain: str) -> DNSCheck:
        records = _lookup(f'_dmarc.{domain}', 'TXT')
        if records is None:
            return DNSCheck(CheckStatus.ERROR, 'DMARC lookup failed')
        if any(r.upper().startswith('V=DMARC1') for r in records):
            return DNSCheck(CheckStatus.PASS, 'DMARC record found')
        return DNSCheck(CheckStatus.FAIL, 'No DMARC record found')

    @staticmethod
    def check(domain_name: str) -> VerificationResult:
        mx = DomainVerificationService.check_mx(domain_name)
        return VerificationResult(
            domain=domain_name,
            mx=mx,
            spf=DomainVerificationService.check_spf(domain_name),
            dkim=DomainVerificationService.check_dkim(domain_name),
            dmarc=DomainVerificationService.check_dmarc(domain_name),
            accepts_mail=mx.status == CheckStatus.PASS,
        )

    @staticmethod
    def verify(domain: Domain) -> VerificationResult:
        """Run all checks and persist the outcome on the domain row."""
        result = DomainVerificationService.check(domain.name)
        fields: dict[str, Any] = {}
        for attr, check in (
            ('mx_verified', result.mx),
            ('spf_verified', result.spf),
            ('dkim_verified', result.dkim),
            ('dmarc_verified', result.dmarc),
        ):
            if check.status == CheckStatus.ERROR:
                continue
            fields[attr] = check.status == CheckStatus.PASS
        if result.accepts_mail and not domain.verified:
            fields['verified'] = True
        changed = [k for k, v in fields.items() if getattr(domain, k) != v]
        if changed:
            for key in changed:
                setattr(domain, key, fields[key])
            domain.save(update_fields=changed)
        return result

    @staticmethod
    def verify_all() -> dict[str, VerificationResult]:
        results = {d.name: DomainVerificationService.verify(d) for d in Domain.objects.all()}
        SystemSettings.set(SettingKey.LAST_VERIFY_AT, timezone.now().isoformat())
        return results
