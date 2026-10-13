"""API versions: what is mounted where, and how a caller finds out.

* ``/api/``       — an unauthenticated index of the versions this server speaks.
* ``/api/v1/...`` — version 1. Within a version only additions are made (new fields, new
  endpoints); removing or changing the meaning of anything means a new version, mounted beside
  the old one, which keeps answering until it is announced as retired in the changelog.
* ``/api/<path>`` — the unversioned spelling used before versions existed. It redirects
  (308, so the method and body are kept) to the same path under ``/api/v1/``.

To add version 2: build its ``NinjaAPI`` (own ``urls_namespace``) next to ``accounts/api.py``,
append an ``ApiVersion`` below and move ``CURRENT`` — nothing else changes.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.http import HttpRequest, HttpResponse, HttpResponsePermanentRedirect, JsonResponse
from django.urls import path, re_path
from ninja import NinjaAPI

from backend.apps.accounts.api import api as api_v1


@dataclass(frozen=True)
class ApiVersion:
    version: str  # "v1"
    status: str  # "current" | "deprecated"
    api: NinjaAPI


VERSIONS: tuple[ApiVersion, ...] = (ApiVersion('v1', 'current', api_v1),)
CURRENT = 'v1'


def index(request: HttpRequest) -> JsonResponse:
    """Which versions exist, where they live and where their contract is."""
    return JsonResponse(
        {
            'current': CURRENT,
            'versions': [
                {
                    'version': v.version,
                    'status': v.status,
                    'url': f'/api/{v.version}/',
                    'openapi': f'/api/{v.version}/openapi.json',
                }
                for v in VERSIONS
            ],
        }
    )


class PermanentRedirect308(HttpResponsePermanentRedirect):
    status_code = 308


def unversioned(request: HttpRequest, rest: str) -> HttpResponse:
    """Old ``/api/<path>`` callers land on the current version without changing anything."""
    query = request.META.get('QUERY_STRING', '')
    target = f'/api/{CURRENT}/{rest}' + (f'?{query}' if query else '')
    response = PermanentRedirect308(target)
    response['Deprecation'] = 'true'
    response['Link'] = f'<{target.split("?")[0]}>; rel="successor-version"'
    return response


urlpatterns = [
    path('api/', index, name='api-index'),
    *[path(f'api/{v.version}/', v.api.urls) for v in VERSIONS],
    re_path(r'^api/(?P<rest>(?!v\d+/).+)$', unversioned, name='api-unversioned'),
]
