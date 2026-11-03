"""The two public addresses campaign tracking uses (Marketing plugin): a pixel and a redirect.

Neither needs a session: the address itself is signed (see ``services/tracking.py``) and only
says which person and which link. A request that is not a person (``HEAD``, a scanner or a bot) is
answered like any other and not counted. Counting never stands in the way of the answer: a click
whose count could not be written still sends the person on.
"""

from __future__ import annotations

import logging

from django.http import HttpRequest, HttpResponse, HttpResponseNotFound, HttpResponseRedirect
from django.views.decorators.csrf import csrf_exempt

from backend.apps.mail.services import tracking

logger = logging.getLogger('backend')

_NO_CACHE = 'no-store, max-age=0'


def _counts(request: HttpRequest) -> bool:
    return request.method == 'GET' and not tracking.is_machine(
        request.META.get('HTTP_USER_AGENT', '')
    )


@csrf_exempt
def marketing_open(request: HttpRequest, token: str) -> HttpResponse:
    """The tracking pixel: a transparent GIF, counting an open."""
    recipient = tracking.read_open_token(token)
    if recipient is None or request.method not in ('GET', 'HEAD'):
        return HttpResponseNotFound()
    try:
        tracking.record_open(recipient, counted=_counts(request))
    except Exception:
        logger.warning('Could not count an open', exc_info=True)
    response = HttpResponse(tracking.PIXEL, content_type='image/gif')
    response['Cache-Control'] = _NO_CACHE
    return response


@csrf_exempt
def marketing_click(request: HttpRequest, token: str) -> HttpResponse:
    """A tracked link: count the click, then send the person to the real address."""
    found = tracking.read_click_token(token)
    if found is None or request.method not in ('GET', 'HEAD'):
        return HttpResponseNotFound()
    recipient, link_id = found
    link = None
    try:
        link = tracking.record_click(recipient, link_id, counted=_counts(request))
    except Exception:
        logger.warning('Could not count a click', exc_info=True)
        link = tracking.record_click(recipient, link_id, counted=False)
    target = tracking.destination(link, recipient) if link is not None else None
    if target is None:
        return HttpResponseNotFound()
    response = HttpResponseRedirect(target)
    response['Cache-Control'] = _NO_CACHE
    response['Referrer-Policy'] = 'no-referrer'
    return response
