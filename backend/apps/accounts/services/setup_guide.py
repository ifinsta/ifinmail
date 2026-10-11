"""What is left before this server sends and receives mail, checked live.

Shown at ``/`` until setup is finished, so whoever just ran the installer can open the server
by its IP address and see, step by step, what to do at the registrar and the VPS provider.
Every value here is public anyway (nameservers, glue, DS, PTR, certificate issuer); no secret
or account detail is ever included. Results are cached briefly because the page is public.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import dns.exception
import dns.resolver
import dns.reversename
from django.core.cache import cache

from backend.apps.dns.services.delegation import DelegationService, _public_resolver
from backend.apps.dns.services.server import DNSServerConfig
from backend.apps.dns.services.zones import ZoneService
from backend.apps.dns.types.zones import DelegationStatus, ZoneMode
from backend.config.env import primary_domain

from .setup_state import SetupState

logger = logging.getLogger('backend')

_CACHE_KEY = 'setup-guide:status'
_CACHE_SECONDS = 30

DONE, ACTION, WAITING, UNKNOWN = 'done', 'action', 'waiting', 'unknown'


@dataclass
class GuideStep:
    key: str
    title: str
    state: str  # done | action | waiting | unknown
    summary: str
    # (label, value) pairs to copy into a registrar or provider form
    values: list[tuple[str, str]] = field(default_factory=list)
    help: str = ''


@dataclass
class GuideStatus:
    domain: str
    mail_hostname: str
    server_ip: str
    steps: list[GuideStep]

    @property
    def done_count(self) -> int:
        return sum(1 for s in self.steps if s.state == DONE)


def _step_nameservers(domain: str, ip: str, status: DelegationStatus) -> GuideStep:
    ns_hosts = list(status.expected_ns)
    values = [('Nameserver', ns) for ns in ns_hosts]
    glue = [h for h in ns_hosts if h == domain or h.endswith(f'.{domain}')]
    values += [(f'Glue record (host → IP): {h}', ip) for h in glue]
    current = ', '.join(status.public_ns) or 'none found'
    if status.delegated:
        return GuideStep(
            'nameservers',
            'Point the domain at this server',
            DONE,
            f'The internet now asks this server about {domain}.',
            values,
        )
    state = UNKNOWN if status.delegated is None else ACTION
    summary = (
        f'At your domain registrar, first add the glue records (often called "host names", '
        f'"child nameservers" or "register nameserver"), then change the nameservers of {domain} '
        f'to the ones below. Currently listed: {current}.'
    )
    if status.serving is False:
        summary += ' Note: this server is not serving the zone yet; see Settings → DNS server.'
    return GuideStep(
        'nameservers',
        'Point the domain at this server',
        state,
        summary,
        values,
        help='Changes usually show within an hour, but can take up to 48 hours.',
    )


def _step_dnssec(domain: str, status: DelegationStatus) -> GuideStep:
    records = ZoneService.ds_records(domain)
    values = [
        (
            'DS record',
            f'Key tag {r.key_tag} · Algorithm {r.algorithm} · Digest type {r.digest_type} · '
            f'Digest {r.digest}',
        )
        for r in records
    ]
    title = 'Turn on DNSSEC (recommended)'
    if not records:
        return GuideStep(
            'dnssec', title, WAITING, 'The zone is still being signed; check back in a minute.'
        )
    if not status.delegated:
        return GuideStep(
            'dnssec',
            title,
            WAITING,
            'After the nameserver change has taken effect, add this DS record at your registrar.',
            values,
        )
    if status.ds_published:
        return GuideStep('dnssec', title, DONE, 'Your registrar publishes the DS record.', values)
    return GuideStep(
        'dnssec',
        title,
        ACTION if status.ds_published is False else UNKNOWN,
        'At your registrar, open the DNSSEC settings of the domain and add this DS record.',
        values,
    )


def _step_reverse_dns(ip: str, mail_hostname: str) -> GuideStep:
    title = 'Set reverse DNS (PTR)'
    values = [('IP address', ip), ('Reverse DNS / PTR name', mail_hostname)]
    help_text = (
        'This is set in your VPS provider’s control panel (often under Networking or the IP '
        'address), not at the registrar. Gmail and Outlook reject or spam-folder mail without it.'
    )
    if not ip:
        return GuideStep('ptr', title, UNKNOWN, 'The server IP address is not known.', values)
    try:
        answer = _public_resolver().resolve(dns.reversename.from_address(ip), 'PTR')
        names = [str(r.target).rstrip('.').lower() for r in answer]
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        names = []
    except (dns.exception.DNSException, OSError, ValueError):
        return GuideStep(
            'ptr', title, UNKNOWN, 'Reverse DNS could not be checked.', values, help_text
        )
    if mail_hostname in names:
        return GuideStep('ptr', title, DONE, f'{ip} points back to {mail_hostname}.', values)
    found = ', '.join(names) or 'nothing'
    return GuideStep(
        'ptr',
        title,
        ACTION,
        f'{ip} currently points to {found}.',
        values,
        help_text,
    )


def _step_certificate(mail_hostname: str, delegated: bool | None) -> GuideStep:
    from backend.apps.core.platform.services.tls import TLSService

    title = 'Trusted TLS certificate'
    cert = TLSService.active_certificate()
    if cert and not cert.self_signed and cert.covers(mail_hostname):
        return GuideStep(
            'tls',
            title,
            DONE,
            f'Issued by {cert.issuer}, valid for {cert.days_left} more days.',
        )
    values = [('Temporary certificate SHA-256', cert.fingerprint_display)] if cert else []
    return GuideStep(
        'tls',
        title,
        WAITING,
        'Let’s Encrypt issues the certificate automatically within a few minutes of the '
        'nameserver change. Until then your browser and mail apps warn about the temporary '
        'self-signed certificate; compare its fingerprint with the one below.'
        if not delegated
        else 'The domain points here; the certificate is being requested and normally '
        'arrives within a few minutes.',
        values,
    )


def _step_mail(domain: str, mail_hostname: str) -> GuideStep:
    from backend.apps.domains.models import Domain

    title = 'Receive mail'
    row = Domain.objects.filter(name=domain).only('verified').first()
    if row and row.verified:
        return GuideStep('mail', title, DONE, f'This server accepts mail for {domain}.')
    return GuideStep(
        'mail',
        title,
        WAITING,
        f'Mail for {domain} is accepted once its MX record ({mail_hostname}) is visible on the '
        'internet. This is checked every 15 minutes and switches on by itself.',
    )


def _collect() -> GuideStatus:
    domain = primary_domain()
    mail_hostname = DNSServerConfig.mail_hostname() or f'mail.{domain}'
    ip = DNSServerConfig.server_ipv4()
    steps = [
        GuideStep(
            'server',
            'Install the server',
            DONE,
            f'All services are running on {ip or "this server"}.',
        )
    ]

    delegated: bool | None = None
    zone = ZoneService.ensure(domain) if domain else None
    if zone is not None and zone.mode == ZoneMode.AUTHORITATIVE.value:
        delegation = DelegationService.check(domain)
        delegated = delegation.delegated
        steps += [_step_nameservers(domain, ip, delegation), _step_dnssec(domain, delegation)]
    else:
        steps.append(
            GuideStep(
                'nameservers',
                'Publish the DNS records',
                ACTION,
                'DNS for this domain is kept at another provider. Sign in and open the setup '
                'wizard to see the exact records to add there.',
            )
        )

    steps += [
        _step_reverse_dns(ip, mail_hostname),
        _step_certificate(mail_hostname, delegated),
        _step_mail(domain, mail_hostname),
    ]
    return GuideStatus(domain=domain, mail_hostname=mail_hostname, server_ip=ip, steps=steps)


class SetupGuide:
    @staticmethod
    def should_show() -> bool:
        return not SetupState.is_marked_complete()

    @staticmethod
    def status() -> GuideStatus | None:
        cached = cache.get(_CACHE_KEY)
        if cached is not None:
            return cached
        try:
            result = _collect()
        except Exception:
            logger.exception('Setup guide checks failed')
            return None
        cache.set(_CACHE_KEY, result, _CACHE_SECONDS)
        return result
