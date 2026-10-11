"""DNS web views — template-rendering views (web flow)."""

import csv
import logging
import os
import re
from collections.abc import Callable
from contextlib import suppress

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from backend.apps.accounts.types.permissions import PermissionCode
from backend.apps.accounts.views.auth import require_perm
from backend.apps.core.platform.services.audit import AuditService
from backend.apps.core.platform.services.monitoring import MonitoringService
from backend.apps.dns.services import PROVIDER_MAP, DNSService
from backend.apps.domains.services import DomainService
from backend.apps.domains.services.provisioning import (
    DomainProvisioningError,
    ProvisioningService,
)
from backend.apps.mail.services.postfix_runtime import OutboundConfigError, PostfixRuntime

from ._helpers import _build_records, _get_server_ip

logger = logging.getLogger('backend')


def _get_dns_status(domain: str) -> dict:
    """Check DNS records via the monitoring service."""
    try:
        return MonitoringService.check_dns(domain)
    except Exception as e:
        logger.warning('DNS status check failed for %s: %s', domain, e)
        return {}


@login_required
@require_perm(PermissionCode.DNS_MANAGE)
def dns_config_page(request: HttpRequest) -> HttpResponse:
    """Render the DNS configuration page."""
    domain = os.environ.get('DOMAIN', os.environ.get('MAIL_DOMAIN', ''))
    server_ip = _get_server_ip()
    outbound = PostfixRuntime.state()
    provider_meta: dict[str, dict[str, object]] = {
        'cloudflare': {
            'help': str(_('Requires an API token with DNS:Edit permission.')),
            'help_url': 'https://developers.cloudflare.com/fundamentals/api/get-started/create-token/',
            'placeholder': 'Cloudflare API Token',
            'second_field': None,
        },
        'porkbun': {
            'help': str(_('Requires API Key and Secret Key from your Porkbun account.')),
            'help_url': 'https://kb.porkbun.com/article/190-getting-started-with-the-porkbun-api',
            'placeholder': 'API Key',
            'second_field': {'name': 'secret_key', 'placeholder': 'Secret Key'},
        },
        'digitalocean': {
            'help': str(_('Requires a personal access token with write access.')),
            'help_url': 'https://docs.digitalocean.com/reference/api/create-personal-access-token/',
            'placeholder': 'DigitalOcean API Token',
            'second_field': None,
        },
    }
    providers = [
        {
            'id': pid,
            'name': cls.provider_name if hasattr(cls, 'provider_name') else pid.capitalize(),
            'fields': fields,
            'label': label,
            'help': provider_meta.get(pid, {}).get('help', ''),
            'help_url': provider_meta.get(pid, {}).get('help_url', ''),
            'placeholder': provider_meta.get(pid, {}).get(
                'placeholder',
                f'{pid.capitalize()} API Token',
            ),
            'second_field': provider_meta.get(pid, {}).get('second_field'),
        }
        for pid, (cls, fields, label) in PROVIDER_MAP.items()
    ]

    saved = DNSService.get_first_config()
    saved_provider = saved.provider if saved else None

    # Extract SPF record from generated DNS records for DNS Toolbox display
    toolbox_spf_record = ''
    if domain and server_ip and server_ip != '0.0.0.0':
        with suppress(Exception):
            records = _build_records(domain, server_ip)
            spf_rec = next((r for r in records if r.type == 'TXT' and r.name == '@'), None)
            if spf_rec:
                toolbox_spf_record = spf_rec.value
    if not toolbox_spf_record:
        toolbox_spf_record = 'v=spf1 mx -all'

    dns_registry_rows = []
    for registered_domain in DomainService.get_all_domains():
        auth_status = []
        auth_status.append('SPF' if registered_domain.spf_verified else 'SPF pending')
        auth_status.append('DKIM' if registered_domain.dkim_verified else 'DKIM pending')
        dns_registry_rows.append(
            {
                'name': registered_domain.name,
                'subtitle': str(_('Verified')) if registered_domain.verified else str(_('Pending')),
                'mx_status': (
                    str(_('MX verified')) if registered_domain.mx_verified else str(_('MX pending'))
                ),
                'mx_status_class': '' if registered_domain.mx_verified else 'warn',
                'auth_records': ' / '.join(auth_status),
                'ssl_expiry': str(_('See TLS health')),
                'actions': '',
            }
        )

    context = {
        'domain': domain,
        'server_ip': server_ip,
        'providers': providers,
        'saved_provider': saved_provider,
        'dns_status': _get_dns_status(domain),
        'dns_registry_headers': [
            _('Domain Name'),
            _('MX Status'),
            _('SPF/DKIM'),
            _('SSL Expiry'),
            _('Actions'),
        ],
        'dns_registry_rows': dns_registry_rows,
        'propagation_sync': str(_('Manual')),
        'propagation_pct': str(_('Unchecked')),
        'dnssec_issues': '0',
        'dnssec_status': str(_('Not monitored')),
        'nameserver_count': str(len(dns_registry_rows)),
        'nameserver_scope': str(_('Configured domains')),
        'cluster_hosts': [],
        'is_mock': False,
        'dkim_selector': os.environ.get('DKIM_SELECTOR', 'default'),
        'toolbox_spf_record': toolbox_spf_record,
        'active_section': 'dns',
        'header_search_placeholder': 'Search domains or records...',
        'smtp_proxy_enabled': outbound.smtp_proxy_enabled,
        'smart_host_enabled': outbound.smart_host_enabled,
        'max_hop_count': outbound.max_hops,
    }
    return render(request, 'admin/dns_config.html', context)


_VALID_DOMAIN_RE = re.compile(r'^(?!-)[a-zA-Z0-9-]{1,63}(?:\.[a-zA-Z0-9-]{1,63})*\.[a-zA-Z]{2,}$')
_VALID_LABEL_RE = re.compile(r'^(?!-)[a-zA-Z0-9-]{1,63}$')


def _normalise_ip(raw: str | None) -> str | None:
    """Validate an optional IP (v4/v6); returns normalised text or raises ValueError."""
    if not raw:
        return None
    import ipaddress as _ip

    try:
        return str(_ip.ip_address(raw.strip()))
    except ValueError:
        raise ValueError('Enter a valid IPv4 or IPv6 address.') from None


def _managed_parent(domain_name: str, explicit_parent: str | None) -> str | None:
    """Longest managed parent of ``domain_name`` (explicit parent first, then DB)."""
    suffix = '.' + explicit_parent if explicit_parent else ''
    is_child = bool(explicit_parent and domain_name.endswith(suffix))
    if is_child and domain_name != explicit_parent:
        return explicit_parent
    try:
        from backend.apps.domains.models import Domain as _Domain

        names = list(_Domain.objects.values_list('name', flat=True))
    except Exception:
        return None
    best: str | None = None
    for cand in names:
        cand = (cand or '').strip().lower()
        if not cand or domain_name == cand:
            continue
        if domain_name.endswith(f'.{cand}') and (best is None or len(cand) > len(best)):
            best = cand
    return best


def _is_subdomain(domain_name: str, parent_domain: str | None) -> bool:
    """Return True if the resolved domain is a subdomain (not a bare parent)."""
    return _managed_parent(domain_name, parent_domain) is not None


@login_required
@require_perm(PermissionCode.DNS_MANAGE)
@require_POST
def dns_register_domain(request: HttpRequest) -> JsonResponse:
    """Register a new domain or subdomain and build its DNS records."""
    raw_domain = request.POST.get('domain', '').strip().lower()
    parent_domain = request.POST.get('parent_domain', '').strip().lower() or None
    ip_address = request.POST.get('ip_address', '').strip() or None

    if not raw_domain or len(raw_domain) > 255:
        return JsonResponse(
            {'status': 'err', 'error': 'Invalid domain name'},
            status=400,
            content_type='application/json; charset=utf-8',
        )

    # Resolve the full domain name.
    if '.' in raw_domain:
        domain_name = raw_domain
    elif parent_domain:
        domain_name = f'{raw_domain}.{parent_domain}'
    else:
        return JsonResponse(
            {'status': 'err', 'error': 'Select a parent domain or enter a full domain name'},
            status=400,
            content_type='application/json; charset=utf-8',
        )

    if not _VALID_DOMAIN_RE.match(domain_name):
        return JsonResponse(
            {'status': 'err', 'error': 'Domain name format is invalid'},
            status=400,
            content_type='application/json; charset=utf-8',
        )

    # IP address: required for subdomains of a managed parent, optional override otherwise.
    # A bare FQDN like ``sub.example.com`` typed without the parent dropdown must not
    # silently drop its IP — detect the parent from the domain table too.
    is_sub = _is_subdomain(domain_name, parent_domain)
    try:
        ip_address = _normalise_ip(ip_address)
    except ValueError as exc:
        return JsonResponse(
            {'status': 'err', 'error': str(exc)},
            status=400,
            content_type='application/json; charset=utf-8',
        )
    if is_sub and not ip_address:
        return JsonResponse(
            {'status': 'err', 'error': 'A valid IP address is required for subdomains'},
            status=400,
            content_type='application/json; charset=utf-8',
        )

    try:
        outcome = ProvisioningService.add_domain(
            domain_name,
            ip_address=ip_address,
            actor=request.user.email if request.user.is_authenticated else None,
        )
        return JsonResponse(
            {
                'status': 'ok' if outcome.ok else 'partial',
                'domain': domain_name,
                'created': outcome.created,
                'records': outcome.dns_records,
                'steps': [
                    {'name': st.name, 'status': str(st.status), 'detail': st.detail}
                    for st in outcome.steps
                ],
                'verification': outcome.verification.as_dict() if outcome.verification else None,
            },
            content_type='application/json; charset=utf-8',
        )
    except DomainProvisioningError as e:
        return JsonResponse(
            {'status': 'err', 'error': str(e)},
            status=400,
            content_type='application/json; charset=utf-8',
        )
    except Exception as e:
        logger.exception('Failed to register domain %s: %s', domain_name, e)
        return JsonResponse(
            {'status': 'err', 'error': 'Could not provision the domain. See the server log.'},
            status=500,
            content_type='application/json; charset=utf-8',
        )


@login_required
@require_perm(PermissionCode.DNS_MANAGE)
def dns_export_records(request: HttpRequest) -> HttpResponse:
    """Export all DNS records as a CSV download."""
    domain_name = os.environ.get('DOMAIN', os.environ.get('MAIL_DOMAIN', ''))
    server_ip = _get_server_ip()
    records = []
    if domain_name and server_ip and server_ip != '0.0.0.0':
        with suppress(Exception):
            records = _build_records(domain_name, server_ip)

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    filename = f'dns_records_{domain_name or "export"}.csv'
    response['Content-Disposition'] = f'attachment; filename={filename}'
    writer = csv.writer(response)
    writer.writerow(['Type', 'Name', 'Value', 'Priority', 'TTL'])
    for r in records:
        writer.writerow([r.type, r.name, r.value, getattr(r, 'priority', ''), r.ttl])
    AuditService.record(
        action='dns_export',
        user=request.user.email if request.user.is_authenticated else None,
        detail=f'Exported {len(records)} records for {domain_name}',
    )
    return response


def _outbound_response(
    request: HttpRequest, action: str, detail: str, change: Callable[[], bool]
) -> JsonResponse:
    """Apply an outbound-mail change, audit it, and report the new state."""
    try:
        enabled = change()
    except OutboundConfigError as exc:
        return JsonResponse(
            {'status': 'err', 'error': str(exc)},
            status=400,
            content_type='application/json; charset=utf-8',
        )
    AuditService.record(
        action=action,
        user=request.user.email if request.user.is_authenticated else None,
        detail=f'{detail} {"enabled" if enabled else "disabled"}',
    )
    return JsonResponse(
        {'status': 'ok', 'enabled': enabled, 'note': 'Applied to Postfix within about 15 seconds.'},
        content_type='application/json; charset=utf-8',
    )


@login_required
@require_perm(PermissionCode.DNS_MANAGE)
@require_POST
def dns_toggle_proxy(request: HttpRequest) -> JsonResponse:
    """Toggle the global SMTP proxy (all outbound mail goes through MAIL_SMTP_PROXY)."""
    return _outbound_response(
        request,
        'smtp_proxy_toggle',
        'SMTP Proxy',
        lambda: (
            PostfixRuntime.set_smtp_proxy(
                not PostfixRuntime.state().smtp_proxy_enabled
            ).smtp_proxy_enabled
        ),
    )


@login_required
@require_perm(PermissionCode.DNS_MANAGE)
@require_POST
def dns_toggle_relay(request: HttpRequest) -> JsonResponse:
    """Toggle the smart-host relay (outbound via MAIL_SMART_HOST)."""
    return _outbound_response(
        request,
        'smart_host_toggle',
        'Smart Host Relay',
        lambda: (
            PostfixRuntime.set_smart_host(
                not PostfixRuntime.state().smart_host_enabled
            ).smart_host_enabled
        ),
    )


@login_required
@require_perm(PermissionCode.DNS_MANAGE)
@require_POST
def dns_set_hop_count(request: HttpRequest) -> JsonResponse:
    """Update Postfix hopcount_limit."""
    try:
        value = int(request.POST.get('value', ''))
        state = PostfixRuntime.set_max_hops(value)
    except (ValueError, TypeError, OutboundConfigError):
        return JsonResponse(
            {'status': 'err', 'error': 'Hop count must be a number from 5 to 30'},
            status=400,
            content_type='application/json; charset=utf-8',
        )
    AuditService.record(
        action='hop_count_update',
        user=request.user.email if request.user.is_authenticated else None,
        detail=f'Set max hop count to {state.max_hops}',
    )
    return JsonResponse(
        {
            'status': 'ok',
            'value': state.max_hops,
            'note': 'Applied to Postfix within about 15 seconds.',
        },
        content_type='application/json; charset=utf-8',
    )
