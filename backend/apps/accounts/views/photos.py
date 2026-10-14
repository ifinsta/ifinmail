"""Profile photos and the contact directory (views -> services).

A person manages their own photo and whether they appear in the directory from the Account page;
an administrator switches the directory on or off from Mailboxes. Photos are served only to
signed-in people who may see them: the owner and anyone who manages mailboxes.
"""

from __future__ import annotations

import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseNotModified
from django.shortcuts import redirect
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from backend.apps.core.platform.services.audit import AuditService

from ..services import directory
from ..services.photos import MAX_UPLOAD_BYTES, Crop, PhotoError, PhotoService
from ..services.roles import RoleService
from ..types.permissions import PermissionCode
from .auth import require_perm

_MAIL = require_perm(PermissionCode.MAIL_MANAGE)


def _sees_others(user: object) -> bool:
    return bool(RoleService.has_perm(user, PermissionCode.MAIL_MANAGE))  # type: ignore[arg-type]


@login_required
@require_GET
def photo_image(request: HttpRequest, user_id: uuid.UUID, size: str) -> HttpResponse:
    """A login's photo as a JPEG (``size`` is ``small`` or ``large``)."""
    if size not in ('small', 'large'):
        raise Http404('unknown size')
    if user_id != request.user.pk and not _sees_others(request.user):
        raise Http404('no photo')
    found = PhotoService.get(user_id, size)
    if found is None:
        raise Http404('no photo')
    body, sha = found
    etag = f'"{sha[:32]}-{size}"'
    if request.headers.get('If-None-Match') == etag:
        not_modified = HttpResponseNotModified()
        not_modified['ETag'] = etag
        return not_modified
    response = HttpResponse(body, content_type='image/jpeg')
    response['ETag'] = etag
    # The URL carries ?v=<hash>, so a new photo is a new URL; private because it is behind a login.
    response['Cache-Control'] = 'private, max-age=86400'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Disposition'] = 'inline; filename="photo.jpg"'
    return response


@login_required
@require_POST
def account_photo_set(request: HttpRequest) -> HttpResponse:
    upload = request.FILES.get('photo')
    if upload is None:
        messages.error(request, _('Choose a picture to upload.'))
        return redirect('accounts:account')
    if upload.size > MAX_UPLOAD_BYTES:
        messages.error(request, _('That picture is larger than 5 MB.'))
        return redirect('accounts:account')
    crop = Crop.parse(
        request.POST.get('crop_x', ''),
        request.POST.get('crop_y', ''),
        request.POST.get('crop_size', ''),
    )
    try:
        PhotoService.set_photo(request.user, upload.read(), crop)
    except PhotoError as exc:
        messages.error(request, str(exc))
        return redirect('accounts:account')
    AuditService.record(action='profile_photo_set', user=request.user.email, detail='self-service')
    messages.success(request, _('Your photo has been saved.'))
    return redirect('accounts:account')


@login_required
@require_POST
def account_photo_remove(request: HttpRequest) -> HttpResponse:
    if PhotoService.remove_photo(request.user):
        AuditService.record(
            action='profile_photo_removed', user=request.user.email, detail='self-service'
        )
        messages.success(request, _('Your photo has been removed.'))
    return redirect('accounts:account')


@login_required
@require_POST
def account_directory_visibility(request: HttpRequest) -> HttpResponse:
    hidden = request.POST.get('visible') != 'on'
    PhotoService.set_directory_hidden(request.user, hidden)
    AuditService.record(
        action='profile_directory_hidden' if hidden else 'profile_directory_shown',
        user=request.user.email,
        detail='self-service',
    )
    messages.success(
        request,
        _('You are hidden from the contact directory.')
        if hidden
        else _('You are shown in the contact directory.'),
    )
    return redirect('accounts:account')


@login_required
@_MAIL
@require_POST
def directory_toggle(request: HttpRequest) -> HttpResponse:
    enabled = request.POST.get('enabled') == 'on'
    directory.DirectoryService.set_enabled(enabled)
    AuditService.record(
        action='contact_directory_toggle',
        user=request.user.email,
        detail='on' if enabled else 'off',
    )
    messages.success(
        request,
        _('The contact directory is on. Contacts apps pick it up within a few minutes.')
        if enabled
        else _('The contact directory is off and has been withdrawn.'),
    )
    return redirect('accounts:mailboxes')
