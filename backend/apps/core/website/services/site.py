"""The public site as one request sees it: which pages exist, the menus, and the footer.

Templates never decide which links to show; they loop over what is built here, so a page that is
off disappears from the header, the footer and every cross-link in one place.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from backend.apps.core.website.services import policy as policy_service
from backend.apps.core.website.types import PAGES, Group, Mode


@dataclass(frozen=True)
class Link:
    key: str  # a page key, or '' for an external link
    label: str
    url: str
    external: bool = False


@dataclass(frozen=True)
class Column:
    title: str
    links: tuple[Link, ...]


@dataclass(frozen=True)
class Site:
    policy: policy_service.Policy
    external: Mapping[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------ pages

    def mode(self, key: str) -> str:
        return self.policy.mode(key)

    def is_on(self, key: str) -> bool:
        return self.mode(key) != Mode.OFF

    @property
    def on(self) -> dict[str, bool]:
        """``site.on.docs`` in templates."""
        return {p.key: self.is_on(p.key) for p in PAGES}

    # ------------------------------------------------------------------ chrome

    @property
    def powered_by(self) -> bool:
        return self.policy.powered_by

    @property
    def project_links(self) -> bool:
        return self.policy.project_links

    @property
    def tagline(self) -> str:
        return self.policy.tagline or str(
            _('A mail server you run yourself, with one console to look after it.')
        )

    @property
    def footer_note(self) -> str:
        return self.policy.footer_note

    @property
    def show_powered_by(self) -> bool:
        return self.powered_by and not self.footer_note

    @property
    def nav_links(self) -> list[Link]:
        labels = {'docs': _('Docs'), 'download': _('Android app')}
        return [
            Link(p.key, str(labels.get(p.key, p.label)), reverse(p.key))
            for p in PAGES
            if p.in_nav and self.is_on(p.key)
        ]

    @property
    def get_started(self) -> Link | None:
        """The header's call to action: the install guide, when there is one."""
        if not self.is_on('docs'):
            return None
        return Link('docs', str(_('Get started')), reverse('docs') + '#install')

    @property
    def home_url(self) -> str:
        return reverse('landing') if self.is_on('landing') else reverse('accounts:login')

    @property
    def footer_columns(self) -> list[Column]:
        def page(key: str, label: str | None = None) -> Link | None:
            if not self.is_on(key):
                return None
            spec = next(p for p in PAGES if p.key == key)
            return Link(key, str(label or spec.label), reverse(key))

        def external(key: str, label: object) -> Link | None:
            url = self.external.get(key, '')
            if not (self.project_links and url):
                return None
            return Link('', str(label), url, external=True)

        install = None
        if self.is_on('docs'):
            install = Link('docs', str(_('Install guide')), reverse('docs') + '#install')
        columns = [
            (
                _('Product'),
                [
                    page('features'),
                    page('pricing'),
                    page('security'),
                    page('changelog'),
                    page('download', str(_('Android app'))),
                ],
            ),
            (
                _('Resources'),
                [
                    page('docs', str(_('Documentation'))),
                    install,
                    external('repo_url', _('Source code')),
                    external('releases_url', _('Releases')),
                ],
            ),
            (
                _('Project'),
                [page('about'), page('contact'), external('issues_url', _('Report an issue'))],
            ),
            (
                _('Legal'),
                [
                    page('terms'),
                    page('privacy'),
                    external('security_policy_url', _('Security policy')),
                ],
            ),
        ]
        out = []
        for title, links in columns:
            present = tuple(link for link in links if link is not None)
            if present:
                out.append(Column(str(title), present))
        return out


def current(external: Mapping[str, str] | None = None) -> Site:
    return Site(policy_service.current(), external or {})


def groups() -> tuple[Group, ...]:
    return tuple(Group)
