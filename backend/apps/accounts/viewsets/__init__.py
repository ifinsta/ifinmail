"""accounts — viewsets: API operation handlers (routers + handlers).

Layer: api.py → viewsets/ → serializers/ → services/ → models/.
Each viewset owns its Ninja router; api.py only assembles them. Routes of other domains live in
that app's own ``api.py`` (see ``backend.apps.mail.api``, ``backend.apps.domains.api``).
"""

from backend.apps.accounts.viewsets.auth import KeyBasic, TokenBearer, actor, require_scope
from backend.apps.accounts.viewsets.status import router as status_router

__all__ = ['KeyBasic', 'TokenBearer', 'actor', 'require_scope', 'status_router']
