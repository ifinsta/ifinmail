"""Server readiness: what is left before this server sends and receives mail, checked live.

Shown on the admin dashboard: step by step, what to do at the registrar and the VPS provider
(nameservers and glue, DNSSEC, reverse DNS), plus what the server finishes by itself once DNS
points here (certificate, inbound mail). Results are cached briefly; the lookups go to public
resolvers.
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
    link: str = ''  # URL name of the console page that completes the step
    link_label: str = ''


@dataclass
class GuideStatus:
    domain: str
    mail_hostname: str
    server_ip: str
    steps: list[GuideStep]

    @property
    def done_count(self) -> int:
        return sum(1 for s in self.steps if s.state == DONE)

    @property
    def ready(self) -> bool:
        return self.done_count == len(self.steps)


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
        link='dns:server',
        link_label='DNS server status',
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
        link='dns:server',
        link_label='DNS server status',
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
        link='accounts:certificates',
        link_label='TLS certificates',
    )


def _step_mail(domain: str, mail_hostname: str) -> GuideStep:
    # Domain.verified only says Postfix will accept the domain (the primary domain is accepted
    # from the start); whether mail can arrive depends on the public MX record.
    from backend.apps.domains.services.verification import DomainVerificationService
    from backend.apps.domains.types.provisioning import CheckStatus

    title = 'Receive mail from the internet'
    mx = DomainVerificationService.check_mx(domain)
    if mx.status == CheckStatus.PASS:
        return GuideStep('mail', title, DONE, f'Other servers deliver mail for {domain} here.')
    if mx.status == CheckStatus.ERROR:
        return GuideStep('mail', title, UNKNOWN, 'The MX record could not be checked.')
    return GuideStep(
        'mail',
        title,
        WAITING,
        f'The server is ready to accept mail for {domain}. Mail arrives once the internet sees '
        f'its MX record pointing at {mail_hostname}, which follows from the nameserver step. '
        f'Now: {mx.detail}.',
    )


def _collect() -> GuideStatus:
    domain = primary_domain()
    mail_hostname = DNSServerConfig.mail_hostname() or f'mail.{domain}'
    ip = DNSServerConfig.server_ipv4()
    steps: list[GuideStep] = []
    if not SetupState.is_complete():
        steps.append(
            GuideStep(
                'mailbox',
                'Create your first mailbox',
                ACTION,
                f'Run the setup wizard to create your own address at {domain}.',
                link='accounts:setup_wizard',
                link_label='Open the setup wizard',
            )
        )

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
                'DNS for this domain is kept at another provider; add the records shown on '
                'the domain page there.',
                link='dns:config',
                link_label='Show the records',
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
    def status(refresh: bool = False) -> GuideStatus | None:
        cached = None if refresh else cache.get(_CACHE_KEY)
        if cached is not None:
            return cached
        try:
            result = _collect()
        except Exception:
            logger.exception('Setup guide checks failed')
            return None
        cache.set(_CACHE_KEY, result, _CACHE_SECONDS)
        return result
