"""domains — serializers: shaping for the API flow.

Layer: api.py → viewsets/ → serializers/ → services/ → models/.
Serializers never touch the database; viewsets feed them service results.
Secrets (DKIM private keys) are never serialized.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ninja import Schema

from backend.apps.domains.models import DKIMKey, Domain
from backend.apps.domains.types.provisioning import ProvisionResult, VerificationResult


@dataclass(frozen=True)
class DomainOut:
    name: str
    verified: bool
    mx_verified: bool
    spf_verified: bool
    dkim_verified: bool
    dmarc_verified: bool

    @classmethod
    def from_model(cls, domain: Domain) -> DomainOut:
        return cls(
            name=domain.name,
            verified=bool(domain.verified),
            mx_verified=bool(domain.mx_verified),
            spf_verified=bool(domain.spf_verified),
            dkim_verified=bool(domain.dkim_verified),
            dmarc_verified=bool(domain.dmarc_verified),
        )


@dataclass(frozen=True)
class DomainStatsOut:
    total: int
    verified: int
    mx_ok: int
    spf_ok: int
    dkim_ok: int
    dmarc_ok: int

    @classmethod
    def from_stats(cls, stats: dict[str, int]) -> DomainStatsOut:
        return cls(
            total=stats.get('total', 0),
            verified=stats.get('verified', 0),
            mx_ok=stats.get('mx_ok', 0),
            spf_ok=stats.get('spf_ok', 0),
            dkim_ok=stats.get('dkim_ok', 0),
            dmarc_ok=stats.get('dmarc_ok', 0),
        )


@dataclass(frozen=True)
class DKIMKeyOut:
    """Public key metadata only — the private key never leaves the service."""

    selector: str
    active: bool

    @classmethod
    def from_model(cls, key: DKIMKey) -> DKIMKeyOut:
        return cls(selector=key.selector, active=bool(key.active))


@dataclass(frozen=True)
class VerificationOut:
    domain: str
    checks: dict[str, dict[str, str]]
    accepts_mail: bool

    @classmethod
    def from_result(cls, result: VerificationResult) -> VerificationOut:
        return cls(
            domain=result.domain,
            checks=result.as_dict(),
            accepts_mail=bool(result.accepts_mail),
        )


@dataclass(frozen=True)
class ProvisionStepOut:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class ProvisionResultOut:
    domain: str
    created: bool
    ok: bool
    steps: list[ProvisionStepOut] = field(default_factory=list)
    dns_records: list[dict[str, str]] = field(default_factory=list)
    nameservers: list[str] = field(default_factory=list)

    @classmethod
    def from_result(cls, result: ProvisionResult) -> ProvisionResultOut:
        return cls(
            domain=result.domain,
            created=bool(result.created),
            ok=bool(result.ok),
            steps=[
                ProvisionStepOut(name=s.name, status=str(s.status), detail=s.detail)
                for s in result.steps
            ],
            dns_records=list(result.dns_records),
            nameservers=list(result.nameservers),
        )


# -- v1 API contract ------------------------------------------------------------------------
# Written out here, not derived from the dataclasses above, so refactoring the internals can never
# change what an integration receives. Within v1 fields are only added, never removed.


class DomainV1(Schema):
    name: str
    verified: bool
    mx_verified: bool
    spf_verified: bool
    dkim_verified: bool
    dmarc_verified: bool


class DomainDetailV1(DomainV1):
    dkim_selectors: list[str]


class DomainCreateV1(Schema):
    name: str


class ProvisionStepV1(Schema):
    name: str
    status: str
    detail: str


class ProvisionResultV1(Schema):
    domain: str
    created: bool
    ok: bool
    steps: list[ProvisionStepV1]
    dns_records: list[dict[str, str]]
    nameservers: list[str]


class VerificationV1(Schema):
    domain: str
    accepts_mail: bool
    checks: dict[str, dict[str, str]]


__all__ = [
    'DKIMKeyOut',
    'DomainCreateV1',
    'DomainDetailV1',
    'DomainOut',
    'DomainV1',
    'ProvisionResultV1',
    'ProvisionStepV1',
    'VerificationV1',
    'DomainStatsOut',
    'ProvisionResultOut',
    'ProvisionStepOut',
    'VerificationOut',
]
