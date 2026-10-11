"""Authoritative DNS pages (web flow: views -> forms -> services)."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from backend.apps.accounts.types.permissions import PermissionCode
from backend.apps.accounts.views.auth import require_perm
from backend.apps.core.platform.services.audit import AuditService
from backend.apps.domains.services import DomainService

from ..forms.zones import (
    RecordAddForm,
    RecordDeleteForm,
    SecondariesForm,
    ZoneForm,
    ZoneModeForm,
)
from ..services.delegation import DelegationService, dns_server_alive
from ..services.records import CustomRecordService, RecordError
from ..services.server import DNSServerConfig
from ..services.zones import ZoneService
from ..types.zones import RecordType, ZoneMode

_DNS = require_perm(PermissionCode.DNS_MANAGE)


def _actor(request: HttpRequest) -> str | None:
    return request.user.email if request.user.is_authenticated else None


def _domain_names() -> list[str]:
    return [d.name for d in DomainService.get_all_domains()]


def _require_zone(name: str) -> str:
    zone = (name or '').strip().lower().rstrip('.')
    if zone not in _domain_names():
        raise Http404(zone)
    return zone


def _first_error(form: object) -> str:
    for field, errors in form.errors.items():  # type: ignore[attr-defined]
        return f'{field.replace("_", " ").capitalize()}: {errors[0]}'
    return 'Please check the form.'


@login_required
@_DNS
@require_GET
def dns_server_page(request: HttpRequest) -> HttpResponse:
    rows = []
    for name in _domain_names():
        view = ZoneService.view(name)
        rows.append(
            {
                'zone': name,
                'mode': view.mode.value,
                'records': len(view.records),
                'ds': bool(view.ds),
            }
        )
    alive, detail = dns_server_alive()
    return render(
        request,
        'admin/settings_dns_server.html',
        {
            'active_section': 'dnsserver',
            'show_settings_icon': True,
            'enabled': DNSServerConfig.enabled(),
            'server_up': alive,
            'server_detail': detail,
            'ns_hosts': DNSServerConfig.ns_hosts(),
            'server_ip': DNSServerConfig.server_ipv4(),
            'server_ipv6': DNSServerConfig.server_ipv6(),
            'secondaries': DNSServerConfig.secondaries(),
            'zones': rows,
        },
    )


@login_required
@_DNS
@require_GET
def dns_zone_page(request: HttpRequest, zone: str) -> HttpResponse:
    zone = _require_zone(zone)
    view = ZoneService.view(zone)
    delegation = DelegationService.check(zone)
    ns_hosts = DNSServerConfig.ns_hosts()
    glue = [h for h in ns_hosts if h == zone or h.endswith(f'.{zone}')]
    return render(
        request,
        'admin/settings_dns_zone.html',
        {
            'active_section': 'dnsserver',
            'show_settings_icon': True,
            'zone': zone,
            'view': view,
            'authoritative': view.mode == ZoneMode.AUTHORITATIVE,
            'delegation': delegation,
            'ns_hosts': ns_hosts,
            'glue_hosts': glue,
            'server_ip': DNSServerConfig.server_ipv4(),
            'record_types': [t.value for t in RecordType],
            'enabled': DNSServerConfig.enabled(),
        },
    )


@login_required
@_DNS
@require_POST
def dns_record_add(request: HttpRequest) -> HttpResponse:
    form = RecordAddForm(request.POST)
    if not form.is_valid():
        messages.error(request, _first_error(form))
        return redirect('dns:server')
    zone = _require_zone(form.cleaned_data['zone'])
    try:
        record = CustomRecordService.add(
            zone,
            name=form.cleaned_data['name'] or '@',
            rtype=form.cleaned_data['rtype'],
            value=form.cleaned_data['value'],
            ttl=form.cleaned_data['ttl'] or 3600,
            priority=form.cleaned_data['priority'],
            managed=ZoneService.managed_records(zone),
        )
    except RecordError as exc:
        messages.error(request, str(exc))
        return redirect('dns:zone', zone=zone)
    ZoneService.publish()
    AuditService.record(action='dns_record_added', user=_actor(request), detail=str(record))
    messages.success(request, f'Added {record.rtype} record for {record.name}.')
    return redirect('dns:zone', zone=zone)


@login_required
@_DNS
@require_POST
def dns_record_delete(request: HttpRequest) -> HttpResponse:
    form = RecordDeleteForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'That record could not be found.')
        return redirect('dns:server')
    zone = _require_zone(form.cleaned_data['zone'])
    if CustomRecordService.delete(zone, str(form.cleaned_data['record_id'])):
        ZoneService.publish()
        AuditService.record(
            action='dns_record_deleted',
            user=_actor(request),
            detail=f'{zone} {form.cleaned_data["record_id"]}',
        )
        messages.success(request, 'Record removed.')
    else:
        messages.error(request, 'That record could not be found.')
    return redirect('dns:zone', zone=zone)


@login_required
@_DNS
@require_POST
def dns_zone_mode(request: HttpRequest) -> HttpResponse:
    form = ZoneModeForm(request.POST)
    if not form.is_valid():
        messages.error(request, _first_error(form))
        return redirect('dns:server')
    zone = _require_zone(form.cleaned_data['zone'])
    mode = ZoneMode(form.cleaned_data['mode'])
    try:
        ZoneService.set_mode(zone, mode)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('dns:zone', zone=zone)
    AuditService.record(action='dns_zone_mode', user=_actor(request), detail=f'{zone} {mode.value}')
    messages.success(
        request,
        f'{zone} is now answered by this server.'
        if mode == ZoneMode.AUTHORITATIVE
        else f'{zone} is now hosted elsewhere. This server no longer answers for it.',
    )
    return redirect('dns:zone', zone=zone)


@login_required
@_DNS
@require_POST
def dns_secondaries(request: HttpRequest) -> HttpResponse:
    form = SecondariesForm(request.POST)
    if not form.is_valid():
        messages.error(request, _first_error(form))
        return redirect('dns:server')
    try:
        saved = DNSServerConfig.set_secondaries(form.address_list())
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('dns:server')
    ZoneService.publish()
    AuditService.record(action='dns_secondaries', user=_actor(request), detail=', '.join(saved))
    messages.success(
        request, 'Secondary nameservers saved.' if saved else 'Secondary nameservers cleared.'
    )
    return redirect('dns:server')


@login_required
@_DNS
@require_POST
def dns_publish(request: HttpRequest) -> HttpResponse:
    form = ZoneForm(request.POST)
    result = ZoneService.publish()
    AuditService.record(action='dns_publish', user=_actor(request), detail=', '.join(result.zones))
    messages.success(request, f'Published {len(result.zones)} zone(s).')
    if form.is_valid() and form.cleaned_data['zone'] in _domain_names():
        return redirect('dns:zone', zone=form.cleaned_data['zone'])
    return redirect('dns:server')
