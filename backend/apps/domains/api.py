"""domains — api.py: the domain routes of the v1 API (urls.py → api.py → viewsets/ contract).

Scope: ``dns.manage``. Adding a domain runs the whole provisioning pipeline (database row, DKIM
key, aliases, DNS records, certificate names, verification) and can take several seconds. Removing
a domain is deliberately not offered: it is a console action that needs a person's confirmation.
"""

from ninja import Router, Status

from backend.apps.accounts.viewsets.auth import ApiRequest, actor, require_scope
from backend.apps.accounts.viewsets.errors import errors, problem
from backend.apps.domains.serializers import (
    DomainCreateV1,
    DomainDetailV1,
    DomainV1,
    ProvisionResultV1,
    ProvisionStepV1,
    VerificationV1,
)
from backend.apps.domains.services.provisioning import DomainProvisioningError

from . import viewsets as ops
from .viewsets import (
    get_domain,
    get_stats,
    list_dkim_keys,
    list_domains,
    provision_domain,
    remove_domain,
    verify_domain,
)

router = Router(tags=['domains'])


def _name(raw: str) -> str:
    return raw.strip().lower().rstrip('.')


@router.get('/domains', response={200: list[DomainV1], **errors()}, summary='List domains')
@require_scope('dns.manage')
def api_list_domains(request: ApiRequest) -> list[DomainV1]:
    """Every hosted domain with its deliverability flags. No keys, no secrets."""
    return [DomainV1(**vars(d)) for d in ops.list_domains()]


@router.get(
    '/domains/{name}', response={200: DomainDetailV1, **errors(404)}, summary='Get a domain'
)
@require_scope('dns.manage')
def api_get_domain(request: ApiRequest, name: str) -> DomainDetailV1:
    domain = ops.get_domain(_name(name))
    if domain is None:
        raise problem(ValueError(f'{_name(name)} does not exist.'))
    selectors = [k.selector for k in ops.list_dkim_keys(domain.name) if k.active]
    return DomainDetailV1(**vars(domain), dkim_selectors=selectors)


@router.post(
    '/domains',
    response={200: ProvisionResultV1, 201: ProvisionResultV1, **errors(422)},
    summary='Add a domain',
)
@require_scope('dns.manage')
def api_create_domain(request: ApiRequest, payload: DomainCreateV1) -> Status[ProvisionResultV1]:
    """Add a domain (idempotent: repeating it repairs whatever is missing). 201 when it is new."""
    try:
        result = ops.provision_domain(payload.name, actor=actor(request))
    except DomainProvisioningError as exc:
        raise problem(exc) from exc
    body = ProvisionResultV1(
        domain=result.domain,
        created=result.created,
        ok=result.ok,
        steps=[ProvisionStepV1(**vars(s)) for s in result.steps],
        dns_records=result.dns_records,
        nameservers=result.nameservers,
    )
    return Status(201 if result.created else 200, body)


@router.post(
    '/domains/{name}/verify',
    response={200: VerificationV1, **errors(404)},
    summary='Verify a domain',
)
@require_scope('dns.manage')
def api_verify_domain(request: ApiRequest, name: str) -> VerificationV1:
    """Check the domain's DNS records against public resolvers. Never changes stored state when
    a lookup fails."""
    result = ops.verify_domain(_name(name))
    if result is None:
        raise problem(ValueError(f'{_name(name)} does not exist.'))
    return VerificationV1(**vars(result))


__all__ = [
    'get_domain',
    'get_stats',
    'list_dkim_keys',
    'list_domains',
    'provision_domain',
    'remove_domain',
    'verify_domain',
]
