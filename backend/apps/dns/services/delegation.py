"""Is this server really the authority for a zone?

Three questions, answered separately so the page can say exactly what is missing:
* serving    - our own DNS container answers for the zone (we publish it correctly);
* delegated  - the public DNS says our nameservers are the zone's nameservers;
* DS         - the registrar holds the DNSSEC key tag, so signatures can be validated.
A lookup that fails to complete never reads as "no": the answer stays unknown (None).
"""

from __future__ import annotations

import logging
import os
import socket

import dns.exception
import dns.flags
import dns.message
import dns.query
import dns.rdatatype
import dns.resolver

from ..types.zones import DelegationStatus, ZoneMode
from .server import DNSServerConfig
from .zones import ZoneService

logger = logging.getLogger('backend')
_DEFAULT_RESOLVERS = ('1.1.1.1', '8.8.8.8', '9.9.9.9')


def _public_resolver() -> dns.resolver.Resolver:
    raw = os.environ.get('DELIVERABILITY_DNS_RESOLVERS', '')
    servers = [r.strip() for r in raw.split(',') if r.strip()] or list(_DEFAULT_RESOLVERS)
    resolver = dns.resolver.Resolver(configure=False)
    resolver.nameservers = servers
    port = os.environ.get('DELIVERABILITY_DNS_PORT', '')
    if port.isdigit():
        resolver.port = int(port)
    resolver.lifetime, resolver.timeout = 6.0, 3.0
    return resolver


def _serving(zone: str) -> tuple[bool | None, str]:
    host, port = DNSServerConfig.query_host(), DNSServerConfig.query_port()
    try:
        address = socket.gethostbyname(host)
    except OSError:
        return None, f'The DNS server ({host}) cannot be reached.'
    query = dns.message.make_query(zone, dns.rdatatype.SOA)
    try:
        try:
            response = dns.query.udp(query, address, port=port, timeout=3)
        except dns.exception.Timeout:
            response = dns.query.tcp(query, address, port=port, timeout=3)
    except (dns.exception.DNSException, OSError):
        return None, 'The DNS server did not answer.'
    answers = response.answer
    if response.flags & dns.flags.AA and any(
        rrset.rdtype == dns.rdatatype.SOA for rrset in answers
    ):
        return True, ''
    return False, 'The DNS server is up but does not serve this zone yet.'


class DelegationService:
    @staticmethod
    def check(zone: str) -> DelegationStatus:
        row = ZoneService.ensure(zone)
        expected = tuple(DNSServerConfig.ns_hosts())
        if row.mode != ZoneMode.AUTHORITATIVE.value:
            return DelegationStatus(zone=zone, expected_ns=expected, detail='Hosted elsewhere.')
        serving, detail = _serving(zone)
        public: tuple[str, ...] = ()
        delegated: bool | None = None
        resolver = _public_resolver()
        try:
            answer = resolver.resolve(zone, 'NS')
            public = tuple(sorted(str(r.target).rstrip('.').lower() for r in answer))
            delegated = bool(public) and set(public) <= set(expected)
            if not delegated and not detail:
                detail = 'The registrar still lists other nameservers.'
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            delegated = False
        except (dns.exception.DNSException, OSError):
            delegated = None
        ds_ok: bool | None = None
        ours = ZoneService.ds_records(zone)
        if ours and delegated:
            try:
                tags = {r.key_tag for r in resolver.resolve(zone, 'DS')}
                ds_ok = {d.key_tag for d in ours} <= tags
            except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
                ds_ok = False
            except (dns.exception.DNSException, OSError):
                ds_ok = None
        return DelegationStatus(
            zone=zone,
            serving=serving,
            delegated=delegated,
            expected_ns=expected,
            public_ns=public,
            ds_published=ds_ok,
            detail=detail,
        )


def dns_server_alive() -> tuple[bool, str]:
    """Does the DNS container answer queries at all?"""
    host, port = DNSServerConfig.query_host(), DNSServerConfig.query_port()
    try:
        address = socket.gethostbyname(host)
        dns.query.udp(dns.message.make_query('.', dns.rdatatype.NS), address, port=port, timeout=2)
    except OSError:
        return False, f'{host} cannot be reached.'
    except dns.exception.DNSException:
        return False, 'The DNS server did not answer.'
    return True, ''
