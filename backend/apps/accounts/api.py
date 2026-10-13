"""accounts — api.py: v1 API assembly (urls.py → api.py → viewsets/ contract).

The integration API (``/api/v1/``). Each app owns the routes of its domain in its own ``api.py``
(``mail``, ``domains``) or ``viewsets/`` (``accounts``: status and metrics); this module only
assembles them and sets how callers authenticate. Every operation is authenticated except
``GET /health`` (liveness). The machine-readable contract is ``/api/v1/openapi.json``; each
operation states ``x-required-scope``.

Authentication: an API key and its secret, as HTTP Basic (``curl -u ifm_<key>:<secret>``) or as one
Bearer value (``ifm.<key>.<secret>``). See ``services.tokens`` and ``viewsets.auth``.

Versioning lives in ``backend/config/api_versions.py``: a breaking change is a new ``NinjaAPI``
instance mounted at ``/api/v2/`` while v1 keeps answering. Within v1 only additions are made.
"""

from backend.apps.accounts.viewsets import KeyBasic, TokenBearer, status_router
from backend.apps.accounts.viewsets.contract import ContractAPI
from backend.apps.core.api import router as health_router
from backend.apps.core.telemetry.api import router as telemetry_router
from backend.apps.dns.api import router as dns_router
from backend.apps.domains.api import router as domains_router
from backend.apps.mail.api import router as mail_router

api = ContractAPI(
    version='1.0.0',
    urls_namespace='api_v1',
    auth=[TokenBearer(), KeyBasic()],
    docs_url=None,
    title='ifinmail API',
    description=(
        'Integration API for the ifinmail mail platform. Authenticate with an API key and '
        'secret (HTTP Basic) or one Bearer token; scopes mirror console permission codes.'
    ),
)

api.add_router('', status_router)
api.add_router('', health_router)
api.add_router('', domains_router)
api.add_router('', dns_router)
api.add_router('', mail_router)
api.add_router('', telemetry_router)

__all__ = ['api']
