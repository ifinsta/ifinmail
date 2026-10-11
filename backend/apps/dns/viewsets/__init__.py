"""dns — viewsets: API operation handlers (API flow).

Layer: api.py → viewsets/ → serializers/ → services/ → models/.
"""

from backend.apps.dns.viewsets.configure import dns_configure
from backend.apps.dns.viewsets.status import dns_status

__all__ = ['dns_configure', 'dns_status']
