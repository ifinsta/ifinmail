"""Domain provisioning viewset — write operations over the provisioning service.

Service errors (unknown domain, mailbox guard) propagate to the caller; the
API layer maps them to status codes. Every step still runs and is reported.
"""

from __future__ import annotations

from backend.apps.domains.serializers import ProvisionResultOut
from backend.apps.domains.services.provisioning import ProvisioningService


def provision_domain(name: str, actor: str | None = None) -> ProvisionResultOut:
    """Run the idempotent add-domain pipeline and shape the outcome."""
    return ProvisionResultOut.from_result(ProvisioningService.add_domain(name, actor=actor))


def remove_domain(name: str, actor: str | None = None) -> bool:
    """Remove a domain (refused while mailboxes exist). False when unknown."""
    return ProvisioningService.remove_domain(name, actor=actor)


__all__ = ['provision_domain', 'remove_domain']
