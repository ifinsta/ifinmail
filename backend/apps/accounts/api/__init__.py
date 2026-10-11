"""First-party v1 API (Bearer tokens, see services.tokens).

Mounted at ``/api/`` (see backend.config.urls). Every operation is
authenticated; there are no anonymous endpoints. The interactive docs UI is
disabled (``docs_url=None``) — the machine-readable contract at
``/api/openapi.json`` is the integration surface. A console-integrated docs
view arrives separately.
"""

from ninja import NinjaAPI

from backend.apps.accounts.api.auth import TokenBearer
from backend.apps.accounts.api.routers_domains import router as domains_router
from backend.apps.accounts.api.routers_status import router as status_router

api = NinjaAPI(
    version='1.0.0',
    urls_namespace='api_v1',
    auth=TokenBearer(),
    docs_url=None,
    title='ifinmail API',
    description='Scoped first-party tokens. Scopes mirror console permission codes.',
)

api.add_router('', status_router)
api.add_router('', domains_router)

__all__ = ['api']
