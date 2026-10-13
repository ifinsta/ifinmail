"""Retrieval negotiation for ``/media/<key>``: how a visitor gets a stored file.

When media is on this server's disk nginx serves it directly and this view is only reached for a
file that is not there. When media is in object storage nginx falls through to here, and the store's
settings decide the answer:

* ``redirect``: a link signed for a few minutes, straight to the storage (the bucket stays private
  and the console does not carry the bytes);
* ``public``: the public or CDN address the administrator gave;
* ``proxy``: the console streams the object (for storage only this server can reach).

Only branding and files marked public are open to anyone; other stored files need a signed-in
administrator, and anything else is a plain 404 (a refusal would confirm the key exists).
"""

from __future__ import annotations

from urllib.parse import quote

from django.http import FileResponse, Http404, HttpRequest, HttpResponse, StreamingHttpResponse
from django.http.response import HttpResponseBase
from django.views.decorators.http import require_GET

from .. import config
from ..contract import InvalidKeyError, ObjectNotFoundError, StorageError, check_key

PUBLIC_PREFIXES = ('branding/',)


def _may_read(request: HttpRequest, key: str) -> bool:
    if key.startswith(PUBLIC_PREFIXES):
        return True
    from backend.apps.core.storage.models import StoredFile
    from backend.apps.core.types.enums import StorageVisibility

    row = StoredFile.objects.filter(file=key).only('visibility').first()
    if row is not None and row.visibility == StorageVisibility.PUBLIC.value:
        return True
    user = getattr(request, 'user', None)
    return bool(user is not None and user.is_authenticated and (user.is_staff or user.is_superuser))


@require_GET
def media(request: HttpRequest, key: str) -> HttpResponseBase:
    try:
        key = check_key(key)
    except InvalidKeyError as exc:
        raise Http404 from exc
    if not _may_read(request, key):
        raise Http404
    chosen = config.external('media')
    if chosen is None:
        store = config.local_store()
        try:
            stream = store.open(key)
            info = store.head(key)
        except (ObjectNotFoundError, StorageError) as exc:
            raise Http404 from exc
        local = StreamingHttpResponse(stream, content_type=info.content_type)
        local['Content-Length'] = str(info.size)
        return local
    store = config.store_for('media')
    if chosen.retrieval == 'public' and chosen.public_base_url:
        prefix = chosen.values.get('prefix', '').strip('/')
        path = f'{prefix}/{key}' if prefix else key
        response = HttpResponse(status=302)
        response['Location'] = f'{chosen.public_base_url}/{quote(path)}'
        response['Cache-Control'] = 'public, max-age=3600'
        return response
    if chosen.retrieval == 'redirect':
        url = store.retrieval_url(key, expires=chosen.url_seconds)
        if url:
            response = HttpResponse(status=302)
            response['Location'] = url
            # The signed link expires: the browser may reuse the redirect only a little less long.
            response['Cache-Control'] = f'private, max-age={max(chosen.url_seconds - 30, 0)}'
            return response
    try:
        info = store.head(key)
        stream = store.open(key)
    except ObjectNotFoundError as exc:
        raise Http404 from exc
    except StorageError:
        return HttpResponse('The file store is not reachable right now.', status=503)
    proxied = StreamingHttpResponse(stream, content_type=info.content_type)
    proxied['Content-Length'] = str(info.size)
    proxied['Cache-Control'] = 'private, max-age=300'
    return proxied


__all__ = ['FileResponse', 'media']
