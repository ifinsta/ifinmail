"""dns — api.py: re-export layer for urls.py → api.py → viewsets/ contract."""

from .viewsets import dns_configure, dns_status, dns_verify_domain

__all__ = ['dns_configure', 'dns_status', 'dns_verify_domain']
