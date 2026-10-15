"""One-click unsubscribe (RFC 8058) for mail sent through the API (Sender compliance plugin).

``GET`` shows a page with one button, so a link scanner or a preview that opens the link
unsubscribes no one. ``POST`` unsubscribes: that is what the button does, and what Gmail,
Yahoo and Outlook send when a person presses their own "Unsubscribe" (the body is
``List-Unsubscribe=One-Click``; there is no session or CSRF token, as the RFC requires).
The link is signed, so it can unsubscribe only the address it was made for, from one domain.
"""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt

from backend.apps.mail.models import Suppression
from backend.apps.mail.services import compliance


@csrf_exempt
def unsubscribe(request: HttpRequest, token: str) -> HttpResponse:
    found = compliance.read_token(token)
    if found is None:
        return render(request, 'mail/unsubscribe.html', {'state': 'invalid'}, status=404)
    domain, address = found
    if request.method == 'POST':
        compliance.suppress(domain, address, Suppression.UNSUBSCRIBED, detail='one-click')
        return render(request, 'mail/unsubscribe.html', {'state': 'done', 'domain': domain, 'address': address})
    if request.method not in ('GET', 'HEAD'):
        return HttpResponse(status=405)
    already = Suppression.objects.filter(domain=domain, address=address).exists()
    return render(
        request,
        'mail/unsubscribe.html',
        {'state': 'done' if already else 'ask', 'domain': domain, 'address': address},
    )
