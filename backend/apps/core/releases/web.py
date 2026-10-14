"""releases — web.py: what devices and visitors read without signing in.

Layer: urls.py → web.py → services/ → models/.

* ``GET /updates/v1/android/latest.json`` — the update manifest the Android app polls. Public and
  read-only on purpose: a phone holds no API key, and the answer is only what the download page
  already shows. ``v1`` is the version of this document; fields are only ever added to it.
* ``GET /download/android/latest.apk`` — a stable link to the newest stable build (for a QR code,
  a chat message or an MDM profile) that redirects to the file.
* ``download_context`` — the facts the public download page renders.
"""

from __future__ import annotations

import base64
import re
from typing import Any

from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse
from django.views.decorators.http import require_GET

from backend.apps.core.releases.services import ReleaseService, manifest_for
from backend.apps.core.releases.types import CHANNEL_VALUES, DEFAULT_CHANNEL, Platform
from backend.config import site_url

_DEVICE_ID = re.compile(r'^[A-Za-z0-9._-]{8,64}$')
HISTORY_LIMIT = 6


def _int(raw: str | None) -> int | None:
    try:
        value = int(raw) if raw is not None and raw != '' else None
    except ValueError:
        return None
    return value if value is not None and 0 <= value < 2**31 else None


def _no_store(response: HttpResponse) -> HttpResponse:
    # Every answer depends on the asking device and on what was published a minute ago.
    response['Cache-Control'] = 'no-store'
    return response


@require_GET
def manifest(request: HttpRequest) -> HttpResponse:
    """``?channel=stable&version_code=12&sdk=34&device=<install id>`` → the update manifest."""
    platform = Platform.ANDROID.value
    channel = request.GET.get('channel', DEFAULT_CHANNEL)
    if channel not in CHANNEL_VALUES:
        return _no_store(
            JsonResponse({'error': 'unknown channel', 'channels': list(CHANNEL_VALUES)}, status=400)
        )
    version_code = _int(request.GET.get('version_code'))
    sdk_int = _int(request.GET.get('sdk')) or 0
    device = request.GET.get('device', '')
    device_id = device if _DEVICE_ID.match(device) else ''

    decision = ReleaseService.check(
        platform=platform,
        channel=channel,
        version_code=version_code,
        sdk_int=sdk_int,
        device_id=device_id,
    )
    if device_id and version_code is not None:
        ReleaseService.record_checkin(
            platform=platform,
            device_id=device_id,
            channel=channel,
            version_code=version_code,
            version_name=request.GET.get('version_name', '')[:64],
            sdk_int=sdk_int,
        )
    body = manifest_for(
        decision,
        platform=platform,
        channel=channel,
        base_url=site_url.origin(request),
    )
    return _no_store(JsonResponse(body))


@require_GET
def latest_apk(request: HttpRequest) -> HttpResponse:
    """302 to the newest stable build, or 404 while nothing is published."""
    release = ReleaseService.latest_published(Platform.ANDROID.value, DEFAULT_CHANNEL)
    if release is None:
        return _no_store(HttpResponse('No Android build has been published yet.', status=404))
    return _no_store(HttpResponseRedirect(ReleaseService.download_path(release)))


_ANDROID_NAMES = {
    21: '5.0', 22: '5.1', 23: '6.0', 24: '7.0', 25: '7.1', 26: '8.0', 27: '8.1', 28: '9',
    29: '10', 30: '11', 31: '12', 32: '12L', 33: '13', 34: '14', 35: '15', 36: '16',
}  # fmt: skip


def android_version(min_sdk: int) -> str:
    """The marketing name of an API level ("24" -> "7.0"), or '' when it is not known."""
    return _ANDROID_NAMES.get(int(min_sdk or 0), '')


def _qr_data_uri(text: str) -> str:
    """An inline SVG QR code for ``text``; empty when the optional library is unavailable."""
    try:
        import qrcode
        from qrcode.image.svg import SvgPathImage
    except ImportError:
        return ''
    try:
        code = qrcode.QRCode(border=2)
        code.add_data(text)
        code.make(fit=True)
        svg = code.make_image(image_factory=SvgPathImage).to_string()
        if isinstance(svg, str):
            svg = svg.encode('utf-8')
        return 'data:image/svg+xml;base64,' + base64.b64encode(svg).decode('ascii')
    except Exception:  # pragma: no cover - a missing QR code must never break the page
        return ''


def download_context(request: HttpRequest) -> dict[str, Any]:
    """Everything the download page shows, so the template only lays it out."""
    platform = Platform.ANDROID.value
    stable = ReleaseService.latest_published(platform, 'stable')
    beta = ReleaseService.latest_published(platform, 'beta')
    if beta is not None and stable is not None and beta.version_code <= stable.version_code:
        beta = None  # a beta older than the stable build is not worth offering
    history = [
        r
        for r in ReleaseService.list_releases(platform, 'stable', published_only=True)[
            : HISTORY_LIMIT + 1
        ]
        if stable is None or r.pk != stable.pk
    ][:HISTORY_LIMIT]
    base = site_url.origin(request)
    permalink = f'{base}/download/android/latest.apk'
    return {
        'release': stable,
        'beta': beta,
        'history': history,
        'download_path': ReleaseService.download_path(stable) if stable else '',
        'beta_path': ReleaseService.download_path(beta) if beta else '',
        'android_version': android_version(stable.min_sdk) if stable else '',
        'permalink': permalink,
        'qr_data_uri': _qr_data_uri(permalink) if stable else '',
        'manifest_url': f'{base}/updates/v1/android/latest.json',
    }


__all__ = ['android_version', 'download_context', 'latest_apk', 'manifest']
