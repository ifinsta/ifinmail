"""domains — viewsets: API operation handlers (API flow).

Layer: api.py → viewsets/ → serializers/ → services/ → models/.
The live HTTP surface for domain inventory is served via the accounts
viewsets; these operations are the mount-ready domain-native layer.
"""

from backend.apps.domains.viewsets.domains import (
    get_domain,
    get_stats,
    list_dkim_keys,
    list_domains,
)
from backend.apps.domains.viewsets.provisioning import provision_domain, remove_domain
from backend.apps.domains.viewsets.verification import verify_domain

__all__ = [
    'get_domain',
    'get_stats',
    'list_dkim_keys',
    'list_domains',
    'provision_domain',
    'remove_domain',
    'verify_domain',
]
