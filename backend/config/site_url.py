"""One answer to "what address is this server at?".

Links that stay inside a page are relative (``{% url %}``): the browser keeps whatever domain the
person is on. Links that *leave* a page — an email, a QR code, an update manifest, a command to
copy — need an absolute address, and they must name the domain people can actually reach:

1. the domain of the current request, when it is a real name (not an IP address, not
   ``localhost``): the person is already there, with a valid certificate;
2. otherwise the configured mail hostname (``MAIL_HOSTNAME``), so a setup link written by an
   administrator who opened the console by IP address still points at the domain;
3. otherwise whatever the request used (a development server on ``localhost``).

Never write a domain into a template or a view. Use ``origin(request)``, ``absolute_url`` or the
``site_origin`` / ``site_host`` template variables.
"""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.http import HttpRequest
from django.urls import reverse


def _bare(host: str) -> str:
    """``host`` without a port (IPv6 literals keep their brackets until parsed)."""
    host = host.strip().lower()
    if host.startswith('['):
        return host.split(']')[0].lstrip('[')
    return host.rsplit(':', 1)[0] if host.count(':') == 1 else host


def is_named_host(host: str) -> bool:
    """True for a DNS name; False for an IP address, ``localhost`` or an empty value."""
    name = _bare(host)
    if not name or name == 'localhost' or name.endswith('.localhost'):
        return False
    try:
        ipaddress.ip_address(name)
    except ValueError:
        return True
    return False


def canonical_host() -> str:
    """The configured public hostname of this server, or ``''`` when none is set."""
    configured = os.environ.get('MAIL_HOSTNAME', '').strip().lower().rstrip('.')
    return configured if is_named_host(configured) else ''


def origin(request: HttpRequest | None = None) -> str:
    """``scheme://host`` for a link that will be read outside the current page."""
    # Context processors can be handed a stand-in (tests, management commands): no get_host,
    # no request.
    usable = request is not None and hasattr(request, 'get_host')
    if usable:
        host = request.get_host()  # type: ignore[union-attr]
        if settings.DEBUG or is_named_host(host):
            return f'{request.scheme}://{host}'  # type: ignore[union-attr]
    canonical = canonical_host()
    if canonical:
        return f'https://{canonical}'
    if usable:
        return f'{request.scheme}://{request.get_host()}'  # type: ignore[union-attr]
    return ''


def host(request: HttpRequest | None = None) -> str:
    """The host part of :func:`origin` (``mail.example.org``), or ``''``."""
    return origin(request).split('://', 1)[-1]


def absolute_url(request: HttpRequest | None, name_or_path: str, *args: Any, **kwargs: Any) -> str:
    """An absolute URL for a URL name (``'accounts:login'``) or a path that starts with ``/``."""
    if name_or_path.startswith('/'):
        path = name_or_path
    else:
        path = reverse(name_or_path, args=args or None, kwargs=kwargs or None)
    return f'{origin(request)}{path}'


def builder(request: HttpRequest | None) -> Callable[[str], str]:
    """A ``path -> absolute URL`` function bound to this request (for email context helpers)."""
    return lambda path: f'{origin(request)}{path}'
