"""Domain inventory viewset — read operations over DomainService."""

from __future__ import annotations

from backend.apps.domains.serializers import DKIMKeyOut, DomainOut, DomainStatsOut
from backend.apps.domains.services import DomainService


def list_domains() -> list[DomainOut]:
    """Every hosted domain with deliverability flags. No keys, no secrets."""
    return [DomainOut.from_model(d) for d in DomainService.get_all_domains()]


def get_domain(name: str) -> DomainOut | None:
    """One domain by name, or None when unknown."""
    row = DomainService.get_domain_by_name(name)
    return DomainOut.from_model(row) if row is not None else None


def get_stats() -> DomainStatsOut | None:
    """Aggregate counts, or None when the database is unreachable."""
    stats = DomainService.get_domain_stats()
    return DomainStatsOut.from_stats(stats) if stats is not None else None


def list_dkim_keys(domain_name: str) -> list[DKIMKeyOut]:
    """Active DKIM selectors for a domain — metadata only, never private keys."""
    return [DKIMKeyOut.from_model(k) for k in DomainService.get_dkim_keys(domain_name)]


__all__ = ['get_domain', 'get_stats', 'list_dkim_keys', 'list_domains']
