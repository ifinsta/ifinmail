"""DNS API views — backwards-compat shim (API flow lives in viewsets/).

New code imports from ``backend.apps.dns.api`` (urls.py → api.py → viewsets/).
"""

from backend.apps.dns.viewsets import dns_configure, dns_status, dns_verify_domain

__all__ = ['dns_configure', 'dns_status', 'dns_verify_domain']
