"""Read-only domain inventory (external monitoring, CMDB sync). Scope: dns.manage."""

from __future__ import annotations

from ninja import Router, Schema

from backend.apps.accounts.api.auth import require_scope
from backend.apps.domains.services import DomainService

router = Router(tags=['domains'])


class DomainOut(Schema):
    name: str
    verified: bool
    mx_verified: bool
    spf_verified: bool
    dkim_verified: bool
    dmarc_verified: bool


@router.get('/domains', response=list[DomainOut])
@require_scope('dns.manage')
def list_domains(request) -> list[DomainOut]:
    """Every hosted domain with deliverability flags. No keys, no secrets."""
    return [
        DomainOut(
            name=row[0],
            verified=bool(row[1]),
            mx_verified=bool(row[2]),
            spf_verified=bool(row[3]),
            dkim_verified=bool(row[4]),
            dmarc_verified=bool(row[5]),
        )
        for row in DomainService.get_domain_verification_rows(
            [d.name for d in DomainService.get_all_domains()]
        )
    ]
