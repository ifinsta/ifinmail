"""The public site: landing, features, pricing, security, docs, changelog, download, about, contact,
terms and privacy. Nobody signs in to read them. None of them reads the database except the
download page, which lists the Android builds an administrator has published.

Copy lives in ``frontend/templates/site/``; this module only routes to it and supplies the few
facts that more than one page quotes (where the code, the issue tracker and the security contact
are). The changelog is the repository's own ``CHANGELOG.md``, so the page and the file cannot
disagree.

Every page first asks ``core.website`` what the "Website pages" plugin decided: serve the page as
shipped (the default, and what happens when the plugin is not installed), serve the
administrator's own text in the same layout, or not serve it at all. The menus and cross-links
come from the same answer, so a page that is off is gone everywhere.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from datetime import date
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import path

from backend.apps.core.releases.web import download_context
from backend.apps.core.website.services import content as website_content
from backend.apps.core.website.services import site as website_site
from backend.apps.core.website.types import BY_KEY, Mode

# The project that publishes the software. One setting (UPDATE_REPO, "owner/name") drives the
# links here, the install command and the release check, so a fork changes it in one place.
REPO = (os.environ.get('UPDATE_REPO', '') or 'ifinsta/ifinmail').strip().strip('/')
REPO_URL = f'https://github.com/{REPO}'
INSTALL_COMMAND = (
    f'curl -sSL https://raw.githubusercontent.com/{REPO}/main/'
    'provisioning/scripts/bootstrap.sh | sudo bash'
)
LEGAL_UPDATED = date(2026, 10, 14)
CHANGELOG_RELEASES = 8  # the page shows the newest releases; the file on GitHub has them all

_HEADING = re.compile(r'(?m)^## (v\d[\w.\-+]*)[ \t]*$')


def _external() -> dict[str, str]:
    return {
        'repo_url': REPO_URL,
        'issues_url': f'{REPO_URL}/issues',
        'releases_url': f'{REPO_URL}/releases',
        'security_policy_url': f'{REPO_URL}/security/policy',
    }


def _context(**extra: object) -> dict[str, object]:
    site = extra.pop('site', None) or website_site.current(_external())
    return {
        **_external(),
        'install_command': INSTALL_COMMAND,
        'legal_updated': LEGAL_UPDATED,
        'site': site,
        **extra,
    }


def _may_preview(request: HttpRequest) -> bool:
    """An administrator may look at a page's own text before switching it on."""
    if request.GET.get('preview') != 'custom':
        return False
    user = request.user
    if not (user.is_authenticated and (user.is_staff or user.is_superuser)):
        return False
    from backend.apps.accounts.services.roles import RoleService
    from backend.apps.accounts.types.permissions import PermissionCode

    return RoleService.has_perm(user, PermissionCode.SYSTEM_MANAGE)


def _serve(
    request: HttpRequest, key: str, standard: Callable[[HttpRequest, dict[str, object]], HttpResponse]
) -> HttpResponse:
    """One public page: off, the administrator's text, or as shipped."""
    site = website_site.current(_external())
    mode = site.mode(key)
    preview = _may_preview(request)
    if mode == Mode.OFF and not preview:
        if key == 'landing':
            return redirect('accounts:login')
        raise Http404(key)
    if mode == Mode.CUSTOM or preview:
        text = website_content.get(key)
        if text.usable:
            return render(
                request,
                'site/custom.html',
                _context(site=site, text=text, page=BY_KEY[key], previewing=preview and mode != Mode.CUSTOM),
            )
    return standard(request, _context(site=site))


def standard_html(request: HttpRequest, key: str) -> str:
    """The page as shipped, whatever the plugin decided: the starting point for custom text."""
    view = _STANDARD[key]
    return view(request, _context()).content.decode('utf-8')


def _page(template: str) -> Callable[[HttpRequest], HttpResponse]:
    key = template.rsplit('/', 1)[-1].removesuffix('.html')

    def standard(request: HttpRequest, context: dict[str, object]) -> HttpResponse:
        return render(request, template, context)

    def view(request: HttpRequest) -> HttpResponse:
        return _serve(request, key, standard)

    view.__name__ = f'{key}_page'
    _STANDARD[key] = standard
    return view


_STANDARD: dict[str, Callable[[HttpRequest, dict[str, object]], HttpResponse]] = {}


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


def _changelog_standard(request: HttpRequest, context: dict[str, object]) -> HttpResponse:
    return render(request, 'site/changelog.html', {**context, 'releases': changelog_releases()})


def _download_standard(request: HttpRequest, context: dict[str, object]) -> HttpResponse:
    """The one public page that reads the database: the newest published Android build."""
    return render(request, 'site/download.html', {**context, **download_context(request)})


_STANDARD['changelog'] = _changelog_standard
_STANDARD['download'] = _download_standard


def changelog_page(request: HttpRequest) -> HttpResponse:
    return _serve(request, 'changelog', _changelog_standard)


def download_page(request: HttpRequest) -> HttpResponse:
    return _serve(request, 'download', _download_standard)


urlpatterns = [
    path('', _page('site/landing.html'), name='landing'),
    path('features/', _page('site/features.html'), name='features'),
    path('pricing/', _page('site/pricing.html'), name='pricing'),
    path('security/', _page('site/security.html'), name='security'),
    path('docs/', _page('site/docs.html'), name='docs'),
    path('changelog/', changelog_page, name='changelog'),
    path('download/', download_page, name='download'),
    path('about/', _page('site/about.html'), name='about'),
    path('contact/', _page('site/contact.html'), name='contact'),
    path('terms/', _page('site/terms.html'), name='terms'),
    path('privacy/', _page('site/privacy.html'), name='privacy'),
]
