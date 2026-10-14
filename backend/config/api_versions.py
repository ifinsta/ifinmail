"""API versions: what is mounted where, how a caller finds out, and what is *not* the API.

* ``/api/``       — an unauthenticated index of the versions this server speaks.
* ``/api/v1/...`` — version 1. Within a version only additions are made (new fields, new
  endpoints); removing or changing the meaning of anything means a new version, mounted beside
  the old one, which keeps answering until it is announced as retired in the changelog.
* ``/api/<path>`` — the unversioned spelling used before versions existed. It redirects
  (308, so the method and body are kept) to the same path under ``/api/v1/``.
* ``LEGACY_MACHINE_PATHS`` — older machine endpoints that lived outside ``/api/`` and now are
  v1 operations; they redirect the same way.

Every JSON endpoint the server has is either a v1 operation or listed below with the reason it is
not: ``INFRASTRUCTURE`` (probes and formats other parties define) and ``CONSOLE`` (calls made by
the console's own pages with the signed-in session and CSRF token, which change with the UI).
A test fails when a new JSON endpoint is in neither place, so "everything is versioned" stays true.

To add version 2: build its ``NinjaAPI`` (own ``urls_namespace``) next to ``accounts/api.py``,
append an ``ApiVersion`` below and move ``CURRENT`` — nothing else changes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from django.http import HttpRequest, HttpResponse, HttpResponsePermanentRedirect, JsonResponse
from django.urls import path, re_path
from ninja import NinjaAPI

from backend.apps.accounts.api import api as api_v1
from backend.apps.accounts.serializers import ApiIndexV1, ApiVersionV1


@dataclass(frozen=True)
class ApiVersion:
    version: str  # "v1"
    status: str  # "current" | "deprecated"
    api: NinjaAPI


VERSIONS: tuple[ApiVersion, ...] = (ApiVersion('v1', 'current', api_v1),)
CURRENT = 'v1'

# Old path (no leading slash) -> path inside the current version.
LEGACY_MACHINE_PATHS: dict[str, str] = {
    'health/full/': 'health/full',
    'health/dns/': 'health/dns',
    'health/deliverability/': 'health/deliverability',
    'telemetry/errors/': 'telemetry/errors',
    'telemetry/stats/': 'telemetry/stats',
    'telemetry/fingerprints/': 'telemetry/fingerprints',
}

# JSON or machine-format endpoints that are not API operations, and why (route -> reason).
INFRASTRUCTURE: dict[str, str] = {
    'health/': 'liveness probe for Docker, nginx and the updater; same body as GET /api/v1/health',
    'csp-report/': 'receiver of browser CSP reports; the format is defined by browsers',
    'manifest.webmanifest': 'web app manifest; the format is defined by browsers',
    'updates/v1/android/latest.json': (
        'update manifest the Android app polls; public and read-only like the download page, '
        'because a phone holds no API key (release management is POST /api/v1/releases/android)'
    ),
}
# Console pages and the calls their own scripts make (signed-in session + CSRF). They change with
# the UI and are not a contract; anything an integration needs is a v1 operation instead.
CONSOLE_PREFIXES: tuple[str, ...] = ('accounts/', 'dns/')
# The three that look most like an API are named so nobody mistakes them for one.
CONSOLE: dict[str, str] = {
    'dns/status/': 'console DNS refresh (session); integrations use GET /api/v1/dns/status',
    'dns/configure/': 'setup wizard stores DNS provider credentials; never offered to keys',
    'dns/verify-domain/': 'console Verify button; integrations use POST /api/v1/domains/{name}/verify',
}


def index(request: HttpRequest) -> JsonResponse:
    """Which versions exist, where they live and where their contract is."""
    body = ApiIndexV1(
        current=CURRENT,
        versions=[
            ApiVersionV1(
                version=v.version,
                status=v.status,
                url=f'/api/{v.version}/',
                openapi=f'/api/{v.version}/openapi.json',
            )
            for v in VERSIONS
        ],
    )
    return JsonResponse(body.model_dump())


class PermanentRedirect308(HttpResponsePermanentRedirect):
    status_code = 308


def _redirect(request: HttpRequest, inside: str) -> HttpResponse:
    query = request.META.get('QUERY_STRING', '')
    target = f'/api/{CURRENT}/{inside}' + (f'?{query}' if query else '')
    response = PermanentRedirect308(target)
    response['Deprecation'] = 'true'
    response['Link'] = f'<{target.split("?")[0]}>; rel="successor-version"'
    return response


def unversioned(request: HttpRequest, rest: str) -> HttpResponse:
    """Old ``/api/<path>`` callers land on the current version without changing anything."""
    return _redirect(request, rest)


def _legacy(inside: str) -> Callable[[HttpRequest], HttpResponse]:
    def view(request: HttpRequest) -> HttpResponse:
        return _redirect(request, inside)

    view.__name__ = 'legacy_' + inside.replace('/', '_')
    return view


urlpatterns = [
    path('api/', index, name='api-index'),
    *[path(f'api/{v.version}/', v.api.urls) for v in VERSIONS],
    re_path(r'^api/(?P<rest>(?!v\d+/).+)$', unversioned, name='api-unversioned'),
    *[path(old, _legacy(new)) for old, new in LEGACY_MACHINE_PATHS.items()],
]
