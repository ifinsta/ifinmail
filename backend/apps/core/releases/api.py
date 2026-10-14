"""releases — api.py: the release-management routes of the v1 API (urls.py → api.py → viewsets/).

Scope: ``system.manage``. This is how a build pipeline (or a person with ``curl``) puts a new
Android build in front of the fleet::

    curl -u ifm_<key>:<secret> -F file=@app-release.apk -F notes="Faster sync" \\
         https://mail.example.org/api/v1/releases/android

Devices never use this API: they read the public manifest at ``/updates/v1/android/latest.json``
(see ``web.py``), which carries no credentials and nothing a visitor could not already download.
"""

from ninja import File, Form, Router, Status, UploadedFile
from ninja.errors import HttpError

from backend.apps.accounts.viewsets.auth import ApiRequest, actor, require_scope
from backend.apps.accounts.viewsets.errors import errors, problem
from backend.apps.core.releases import viewsets as ops
from backend.apps.core.releases.serializers import (
    ReleaseChangeV1,
    ReleaseOverviewV1,
    ReleasePublishV1,
    ReleaseV1,
)

router = Router(tags=['releases'])


@router.get(
    '/releases/{platform}',
    response={200: ReleaseOverviewV1, **errors(404)},
    summary='List app releases',
)
@require_scope('system.manage')
def api_list_releases(
    request: ApiRequest, platform: str, channel: str | None = None
) -> ReleaseOverviewV1:
    """Every release (published or not) with how many active devices run each version."""
    try:
        return ops.overview(platform, channel)
    except ValueError as exc:
        raise problem(exc) from exc


@router.post(
    '/releases/{platform}',
    response={201: ReleaseV1, **errors(404, 409, 422)},
    summary='Publish an app release',
)
@require_scope('system.manage')
def api_publish_release(
    request: ApiRequest,
    platform: str,
    form: Form[ReleasePublishV1],
    file: File[UploadedFile | None] = None,
) -> Status[ReleaseV1]:
    """Upload a signed APK. The server reads its version and certificate itself; it refuses a file
    for another application, an unsigned one, a repeated version code or one signed with a
    different key than the releases before it."""
    # Optional in the signature so that the scope check (above) always answers before validation
    # does; a missing file is reported here, once the caller is known to be allowed.
    if file is None:
        raise HttpError(422, 'Send the APK as the multipart field "file".')
    try:
        return Status(201, ops.publish(platform, file, form, actor=actor(request)))
    except ValueError as exc:
        raise problem(exc) from exc


@router.patch(
    '/releases/{platform}/{channel}/{version_code}',
    response={200: ReleaseV1, **errors(404, 422)},
    summary='Change a release',
)
@require_scope('system.manage')
def api_change_release(
    request: ApiRequest, platform: str, channel: str, version_code: str, body: ReleaseChangeV1
) -> ReleaseV1:
    """Edit notes, withdraw or restore a release, make it mandatory or set its rollout share."""
    try:
        return ops.change(platform, channel, version_code, body, actor=actor(request))
    except ValueError as exc:
        raise problem(exc) from exc


@router.delete(
    '/releases/{platform}/{channel}/{version_code}',
    response={204: None, **errors(404)},
    summary='Delete a release',
)
@require_scope('system.manage')
def api_delete_release(
    request: ApiRequest, platform: str, channel: str, version_code: str
) -> Status[None]:
    """Remove the release and its file. Prefer withdrawing it (``is_published: false``)."""
    try:
        ops.remove(platform, channel, version_code, actor=actor(request))
    except ValueError as exc:
        raise problem(exc) from exc
    return Status(204, None)


__all__ = ['router']
