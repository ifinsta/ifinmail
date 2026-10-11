"""dns — api.py: re-export layer for urls.py → api.py → viewsets/ contract."""

from .viewsets import dns_configure, dns_status

__all__ = ['dns_configure', 'dns_status']
