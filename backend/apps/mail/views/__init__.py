"""Mail views for ifinmail: client autoconfiguration and the MTA-STS policy.

These endpoints are reached on per-domain hostnames (``autoconfig.<domain>``,
``autodiscover.<domain>``, ``mta-sts.<domain>``). nginx forwards them to the
api with the mail hostname as ``Host`` (so Django's ALLOWED_HOSTS stays strict)
and the hostname the client used in ``X-Original-Host``.
"""

from __future__ import annotations

import os
import re
from xml.sax.saxutils import escape as xml_escape

from django.http import Http404, HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from backend.apps.domains.models import Domain
from backend.apps.mail.services.mta_sts import MtaStsService

_EMAIL_RE = re.compile(r'^[^@\s<>&"\']{1,64}@([A-Za-z0-9.-]{1,253})$')
_AUTODISCOVER_EMAIL_RE = re.compile(rb'<EMailAddress>\s*([^<\s]{3,254})\s*</EMailAddress>', re.I)
_MAX_BODY = 8192
_CACHE = 'public, max-age=3600'


def _mail_hostname() -> str:
    return os.environ.get('MAIL_HOSTNAME', '')


def _requested_host(request: HttpRequest) -> str:
    raw = request.headers.get('X-Original-Host') or request.get_host()
    return raw.split(':', 1)[0].strip().lower()


def _hosted_domain(name: str) -> str | None:
    return name if name and Domain.objects.filter(name=name).exists() else None


def _client_domain(request: HttpRequest, email: str = '') -> str:
    """The domain a client is configuring, or '' to use the primary domain.

    Raises Http404 when a specific domain was asked for but is not hosted here.
    """
    match = _EMAIL_RE.match(email or request.GET.get('emailaddress', ''))
    if match:
        domain = _hosted_domain(match.group(1).lower())
        if domain is None:
            raise Http404('Unknown domain')
        return domain
    host = _requested_host(request)
    for prefix in ('autoconfig.', 'autodiscover.'):
        if host.startswith(prefix):
            domain = _hosted_domain(host[len(prefix) :])
            if domain is None:
                raise Http404('Unknown domain')
            return domain
    return os.environ.get('MAIL_DOMAIN', os.environ.get('DOMAIN', ''))


@require_http_methods(['GET'])
def autoconfig_mozilla(request: HttpRequest) -> HttpResponse:
    """Thunderbird / Mozilla autoconfig XML for the requested domain."""
    d = xml_escape(_client_domain(request))
    h = xml_escape(_mail_hostname())
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<clientConfig version="1.1">
    <emailProvider id="{d}">
        <domain>{d}</domain>
        <displayName>{d} Mail</displayName>
        <displayShortName>{d}</displayShortName>
        <incomingServer type="imap">
            <hostname>{h}</hostname>
            <port>993</port>
            <socketType>SSL</socketType>
            <authentication>password-cleartext</authentication>
            <username>%EMAILADDRESS%</username>
        </incomingServer>
        <incomingServer type="pop3">
            <hostname>{h}</hostname>
            <port>995</port>
            <socketType>SSL</socketType>
            <authentication>password-cleartext</authentication>
            <username>%EMAILADDRESS%</username>
        </incomingServer>
        <outgoingServer type="smtp">
            <hostname>{h}</hostname>
            <port>587</port>
            <socketType>STARTTLS</socketType>
            <authentication>password-cleartext</authentication>
            <username>%EMAILADDRESS%</username>
        </outgoingServer>
    </emailProvider>
</clientConfig>"""
    response = HttpResponse(xml, content_type='application/xml')
    response['Cache-Control'] = _CACHE
    return response


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def autoconfig_outlook(request: HttpRequest) -> HttpResponse:
    """Outlook / Microsoft autodiscover XML (clients POST their address)."""
    email = ''
    if request.method == 'POST':
        found = _AUTODISCOVER_EMAIL_RE.search(request.body[:_MAX_BODY])
        email = found.group(1).decode('utf-8', errors='ignore') if found else ''
    _client_domain(request, email)  # 404 for domains that are not hosted here
    login = xml_escape(email) if _EMAIL_RE.match(email) else '%EMAILADDRESS%'
    h = xml_escape(_mail_hostname())
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<Autodiscover xmlns="http://schemas.microsoft.com/exchange/autodiscover/responseschema/2006">
  <Response xmlns="http://schemas.microsoft.com/exchange/autodiscover/outlook/responseschema/2006a">
    <Account>
      <AccountType>email</AccountType>
      <Action>settings</Action>
      <Protocol>
        <Type>IMAP</Type>
        <Server>{h}</Server>
        <Port>993</Port>
        <LoginName>{login}</LoginName>
        <SPA>off</SPA>
        <SSL>on</SSL>
      </Protocol>
      <Protocol>
        <Type>POP3</Type>
        <Server>{h}</Server>
        <Port>995</Port>
        <LoginName>{login}</LoginName>
        <SPA>off</SPA>
        <SSL>on</SSL>
      </Protocol>
      <Protocol>
        <Type>SMTP</Type>
        <Server>{h}</Server>
        <Port>587</Port>
        <LoginName>{login}</LoginName>
        <SPA>off</SPA>
        <Encryption>TLS</Encryption>
      </Protocol>
    </Account>
  </Response>
</Autodiscover>"""
    response = HttpResponse(xml, content_type='application/xml')
    response['Cache-Control'] = 'no-cache'
    return response


@require_http_methods(['GET'])
def mta_sts_policy(request: HttpRequest) -> HttpResponse:
    """RFC 8461 policy, served at https://mta-sts.<domain>/.well-known/mta-sts.txt."""
    host = _requested_host(request)
    if not host.startswith('mta-sts.') or _hosted_domain(host[len('mta-sts.') :]) is None:
        raise Http404('No MTA-STS policy for this host')
    body = MtaStsService.policy_text(_mail_hostname())
    response = HttpResponse(body, content_type='text/plain; charset=utf-8')
    response['Cache-Control'] = _CACHE
    return response
