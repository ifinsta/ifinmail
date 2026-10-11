"""domains — api.py: re-export layer for urls.py → api.py → viewsets/ contract."""

from .viewsets import (
    get_domain,
    get_stats,
    list_dkim_keys,
    list_domains,
    provision_domain,
    remove_domain,
    verify_domain,
)

__all__ = [
    'get_domain',
    'get_stats',
    'list_dkim_keys',
    'list_domains',
    'provision_domain',
    'remove_domain',
    'verify_domain',
]
