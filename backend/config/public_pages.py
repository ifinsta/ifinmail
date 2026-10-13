"""The public site: landing, features, pricing, security, docs, changelog, about, contact, terms
and privacy. Nobody signs in to read them, and none of them reads the database.

Copy lives in ``frontend/templates/site/``; this module only routes to it and supplies the few
facts that more than one page quotes (where the code, the issue tracker and the security contact
are). The changelog is the repository's own ``CHANGELOG.md``, so the page and the file cannot
disagree.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import path

REPO_URL = 'https://github.com/ifinsta/ifinmail'
INSTALL_COMMAND = (
    'curl -sSL https://raw.githubusercontent.com/ifinsta/ifinmail/main/'
    'provisioning/scripts/bootstrap.sh | sudo bash'
)
LEGAL_UPDATED = date(2026, 10, 13)
CHANGELOG_RELEASES = 8  # the page shows the newest releases; the file on GitHub has them all

_HEADING = re.compile(r'(?m)^## (v\d[\w.\-+]*)[ \t]*$')


def _context(**extra: object) -> dict[str, object]:
    return {
        'repo_url': REPO_URL,
        'issues_url': f'{REPO_URL}/issues',
        'releases_url': f'{REPO_URL}/releases',
        'security_policy_url': f'{REPO_URL}/security/policy',
        'install_command': INSTALL_COMMAND,
        'legal_updated': LEGAL_UPDATED,
        **extra,
    }


def _page(template: str) -> Callable[[HttpRequest], HttpResponse]:
    def view(request: HttpRequest) -> HttpResponse:
        return render(request, template, _context())

    view.__name__ = template.rsplit('/', 1)[-1].removesuffix('.html') + '_page'
    return view


def parse_changelog(text: str, limit: int = CHANGELOG_RELEASES) -> list[dict[str, str]]:
    """``[{version, anchor, body}]`` newest first, from ``## vX.Y.Z`` sections."""
    parts = _HEADING.split(text)
    releases = []
    for version, body in zip(parts[1::2], parts[2::2], strict=False):
        releases.append(
            {
                'version': version,
                'anchor': re.sub(r'[^a-z0-9]+', '-', version.lower()).strip('-'),
                'body': body.strip('\n'),
            }
        )
    return releases[:limit]


@lru_cache(maxsize=2)
def _changelog(path_str: str, mtime_ns: int) -> tuple[dict[str, str], ...]:
    """Parsed once per version of the file (``mtime_ns`` is the cache key)."""
    return tuple(parse_changelog(Path(path_str).read_text(encoding='utf-8')))


def changelog_releases() -> list[dict[str, str]]:
    """The newest releases; empty when the file is not shipped with this install."""
    file = Path(settings.BASE_DIR) / 'CHANGELOG.md'
    try:
        return list(_changelog(str(file), file.stat().st_mtime_ns))
    except OSError:
        return []


def changelog_page(request: HttpRequest) -> HttpResponse:
    return render(request, 'site/changelog.html', _context(releases=changelog_releases()))


urlpatterns = [
    path('', _page('site/landing.html'), name='landing'),
    path('features/', _page('site/features.html'), name='features'),
    path('pricing/', _page('site/pricing.html'), name='pricing'),
    path('security/', _page('site/security.html'), name='security'),
    path('docs/', _page('site/docs.html'), name='docs'),
    path('changelog/', changelog_page, name='changelog'),
    path('about/', _page('site/about.html'), name='about'),
    path('contact/', _page('site/contact.html'), name='contact'),
    path('terms/', _page('site/terms.html'), name='terms'),
    path('privacy/', _page('site/privacy.html'), name='privacy'),
]
