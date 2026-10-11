"""Setup wizard views."""

import logging
import os
import re

from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from backend.apps.accounts.services.setup_state import SetupState
from backend.apps.dns.services import DNSService
from backend.apps.domains.services.provisioning import (
    DomainProvisioningError,
    ProvisioningService,
)
from backend.apps.mail.services import MailboxService
from backend.apps.mail.types.provisioning import MailboxError
from backend.services.audit import AuditService

from ..types.permissions import PermissionCode
from ._constants import _DOMAIN_RE, _IPIFY_URL
from .auth import require_perm

logger = logging.getLogger('backend')


def _validate_domain(name: str) -> str:
    """Validate and normalize a domain name. Returns empty string if invalid."""
    if not name or len(name) > 253:
        return ''
    name = re.sub(r'^https?://', '', name.strip().lower())
    name = name.rstrip('.')
    if _DOMAIN_RE.match(name):
        return name
    return ''


def _setup_is_complete() -> bool:
    """True once setup was finished (or an install already has mailboxes)."""
    return SetupState.is_complete()


def _setup_server_ip() -> str:
    ip_check_url = os.environ.get('IP_CHECK_URL', _IPIFY_URL)
    try:
        import requests as req

        resp = req.get(ip_check_url, timeout=5)
        if resp.status_code == 200:
            ip = resp.text.strip()
            if ip.startswith(('10.', '172.', '192.168.', '127.')):
                logger.warning('Detected private IP %s — DNS records may be wrong', ip)
            return ip
    except Exception as e:
        logger.warning('Failed to detect server IP via %s: %s', ip_check_url, e)
    try:
        import socket

        return socket.gethostbyname(socket.gethostname())
    except Exception as e:
        logger.warning('Failed to resolve hostname: %s', e)
        return '0.0.0.0'


def _create_first_account(email: str, password: str, request: HttpRequest) -> str:
    """Create the first mailbox and its administrator login. Returns an error message or ''."""
    local_part, _, domain_name = email.strip().lower().partition('@')
    if not domain_name:
        return 'Enter a full email address such as you@example.com.'
    try:
        ProvisioningService.add_domain(domain_name, actor=request.user.email, verify=False)
        _, user = MailboxService.create(
            domain_name,
            local_part,
            password,
            is_admin=True,
            adopt_existing_login=True,
        )
        if user.pk == request.user.pk:
            # The administrator just set their own password: keep them signed in.
            update_session_auth_hash(request, user)
    except (MailboxError, DomainProvisioningError) as exc:
        return str(exc)
    except Exception:
        logger.exception('Failed to create first account during setup')
        return 'Could not create the account. See the server log for details.'
    AuditService.record(
        'account_created',
        user=request.user.email,
        detail=email,
        severity='info',
    )
    return ''


@login_required
@require_perm(PermissionCode.SETUP_MANAGE)
def setup_wizard(request: HttpRequest) -> HttpResponse:
    """Redirect to the current setup wizard step."""
    if _setup_is_complete():
        return redirect('accounts:dashboard')
    return redirect('accounts:setup_step', step='welcome')


@login_required
@require_perm(PermissionCode.SETUP_MANAGE)
def setup_step(request: HttpRequest, step: str) -> HttpResponse:
    """Render a setup wizard step."""
    if SetupState.is_marked_complete():
        return redirect('accounts:dashboard')

    domain = request.session.get('setup_domain') or os.environ.get('DOMAIN', '')
    dns_provider = request.session.get('setup_dns_provider', '')
    server_ip = _setup_server_ip()

    context = {
        'step': step,
        'domain': domain,
        'dns_provider': dns_provider,
        'server_ip': server_ip,
    }

    if step == 'welcome':
        template = 'setup/welcome.html'
    elif step == 'dns-server':
        template = 'setup/dns_server.html'
        if not domain:
            return redirect('accounts:setup_step', step='dns')
        from backend.apps.dns.services.server import DNSServerConfig
        from backend.apps.dns.services.zones import ZoneService

        ns_hosts = DNSServerConfig.ns_hosts()
        context['ns_hosts'] = ns_hosts
        context['glue_hosts'] = [h for h in ns_hosts if h == domain or h.endswith(f'.{domain}')]
        context['server_ip'] = DNSServerConfig.server_ipv4()
        context['dns_records'] = [
            {
                'type': r.type,
                'name': domain if r.name == '@' else f'{r.name}.{domain}',
                'value': f'{r.priority} {r.value}' if r.type == 'MX' else r.value,
            }
            for r in ZoneService.managed_records(domain)
        ]
    elif step == 'dns':
        template = 'setup/dns_provider.html'
        from backend.apps.dns.services.server import DNSServerConfig

        context['authoritative_available'] = DNSServerConfig.enabled()
        from django.utils.translation import gettext_lazy as _

        from backend.apps.dns.services import PROVIDER_MAP

        provider_meta = {
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
        context['providers'] = [
            {
                'id': pid,
                'name': cls.provider_name if hasattr(cls, 'provider_name') else pid.capitalize(),
                'help': provider_meta.get(pid, {}).get('help', ''),
                'help_url': provider_meta.get(pid, {}).get('help_url', ''),
                'placeholder': provider_meta.get(pid, {}).get(
                    'placeholder', f'{pid.capitalize()} API Token'
                ),
                'second_field': provider_meta.get(pid, {}).get('second_field'),
            }
            for pid, (cls, fields, label) in PROVIDER_MAP.items()
        ]
    elif step == 'dns-auto':
        template = 'setup/dns_auto.html'
        if not domain:
            return redirect('accounts:setup_step', step='dns')
    elif step == 'dns-manual':
        template = 'setup/dns_manual.html'
        if not domain:
            return redirect('accounts:setup_step', step='dns')
        if domain and server_ip and server_ip != '0.0.0.0':
            raw_records = DNSService.build_records(domain, server_ip)
            dns_records = []
            for rec in raw_records:
                display_name = rec.name if rec.name != '@' else ''
                if display_name and not display_name.startswith('_') or display_name:
                    display_name = f'{rec.name}.{domain}'
                elif rec.type == 'A':
                    display_name = domain  # root A record shows bare domain
                else:
                    display_name = domain
                value = rec.value
                if rec.type == 'MX':
                    value = f'{rec.priority} {rec.value}'
                elif rec.type == 'TXT':
                    value = f'"{rec.value}"'
                dns_records.append(
                    {
                        'type': rec.type,
                        'name': display_name,
                        'value': value,
                    }
                )
            context['dns_records'] = dns_records
    elif step == 'account':
        template = 'setup/create_account.html'
        context['error'] = request.session.pop('setup_error', '')
    elif step == 'done':
        template = 'setup/done.html'
    else:
        return redirect('accounts:setup_step', step='welcome')

    return render(request, template, context)


def _wizard_set_zone_mode(domain: str, authoritative: bool, request: HttpRequest) -> str:
    """Choose who answers DNS for ``domain``; returns the next wizard step."""
    from backend.apps.dns.services.zones import ZoneService
    from backend.apps.dns.types.zones import ZoneMode

    try:
        ZoneService.set_mode(domain, ZoneMode.AUTHORITATIVE if authoritative else ZoneMode.EXTERNAL)
    except Exception:
        logger.exception('Could not set the DNS mode for %s', domain)
        return 'dns'
    return 'dns-server' if authoritative else 'dns-manual'


@login_required
@require_perm(PermissionCode.SETUP_MANAGE)
def setup_advance(request: HttpRequest) -> HttpResponse:
    """POST handler that advances the wizard one step."""
    if request.method != 'POST':
        return redirect('accounts:setup_step', step='welcome')

    if SetupState.is_marked_complete():
        return redirect('accounts:dashboard')

    current = request.POST.get('current_step', 'welcome')
    skip = request.POST.get('skip', '') == '1'

    if current == 'welcome':
        domain = request.POST.get('domain', '').strip()
        if domain and not skip:
            valid_domain = _validate_domain(domain)
            if not valid_domain:
                AuditService.record(
                    'setup_invalid_domain',
                    user=request.user.email,
                    detail=f'Rejected invalid domain: {domain}',
                    severity='warn',
                )
                return redirect('accounts:setup_step', step='welcome')
            request.session['setup_domain'] = valid_domain
            try:
                ProvisioningService.add_domain(valid_domain, actor=request.user.email, verify=False)
            except Exception as e:
                logger.exception('Failed to provision domain %s during setup: %s', valid_domain, e)
        next_step = 'dns'

    elif current == 'dns':
        choice = request.POST.get('choice', '')
        domain = request.session.get('setup_domain') or os.environ.get('DOMAIN', '')
        if choice == 'authoritative' and domain:
            next_step = _wizard_set_zone_mode(domain, True, request)
        elif choice == 'manual' and domain:
            _wizard_set_zone_mode(domain, False, request)
            next_step = 'dns-manual'
        elif not skip:
            provider = request.POST.get('provider', '')
            request.session['setup_dns_provider'] = provider
            if provider and domain:
                _wizard_set_zone_mode(domain, False, request)
            next_step = 'dns-auto' if provider else 'account'
        else:
            next_step = 'account'

    elif current in ('dns-auto', 'dns-manual', 'dns-server'):
        next_step = 'account'

    elif current == 'account':
        if not skip:
            email = request.POST.get('email', '').strip()
            password = request.POST.get('password', '')
            if email and password:
                error = _create_first_account(email, password, request)
                if error:
                    request.session['setup_error'] = error
                    return redirect('accounts:setup_step', step='account')
        next_step = 'done'

    elif current == 'done':
        # Clear session state on completion
        request.session.pop('setup_domain', None)
        request.session.pop('setup_dns_provider', None)
        SetupState.mark_complete()
        response = redirect('accounts:dashboard')
        return response

    else:
        next_step = 'welcome'

    return redirect('accounts:setup_step', step=next_step)
