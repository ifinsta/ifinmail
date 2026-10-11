"""accounts — viewsets: API operation handlers (routers + handlers).

Layer: api.py → viewsets/ → serializers/ → services/ → models/.
Each viewset owns its Ninja router; api.py only assembles them.
"""

from backend.apps.accounts.viewsets.auth import TokenBearer, require_scope
from backend.apps.accounts.viewsets.domains import router as domains_router
from backend.apps.accounts.viewsets.status import router as status_router

__all__ = ['TokenBearer', 'domains_router', 'require_scope', 'status_router']
