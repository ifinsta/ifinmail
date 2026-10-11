"""Domain verification viewset — read-only checks over the verification service."""

from __future__ import annotations

from backend.apps.domains.serializers import VerificationOut
from backend.apps.domains.services import DomainService
from backend.apps.domains.services.verification import DomainVerificationService


def verify_domain(name: str) -> VerificationOut | None:
    """Verify a hosted domain's DNS records, or None when the domain is unknown.

    Lookups that fail never change stored state (see verification service).
    """
    row = DomainService.get_domain_by_name(name)
    if row is None:
        return None
    return VerificationOut.from_result(DomainVerificationService.verify(row))


__all__ = ['verify_domain']
