"""The public website's pages and what an administrator may decide about each."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

CAPABILITY = 'website.pages'
TARGET = 'console.website'
PLUGIN_ID = 'website-pages'


class Mode(StrEnum):
    STANDARD = 'standard'  # the page as shipped
    CUSTOM = 'custom'  # the administrator's own text in the same layout
    OFF = 'off'  # not served: 404, or the sign-in page for the home page


MODES = tuple(str(m) for m in Mode)


class Group(StrEnum):
    PRODUCT = 'product'
    RESOURCES = 'resources'
    PROJECT = 'project'
    LEGAL = 'legal'


@dataclass(frozen=True)
class Page:
    key: str  # also the URL name in backend/config/public_pages.py
    label: str
    summary: str
    group: Group
    # In the header menu (the footer lists every page that is on).
    in_nav: bool = False
    # Says things about the open-source project itself (not about the organisation running it).
    about_project: bool = False


PAGES: tuple[Page, ...] = (
    Page('landing', 'Home', 'The front page.', Group.PRODUCT),
    Page('features', 'Features', 'What the platform does.', Group.PRODUCT, in_nav=True),
    Page('pricing', 'Pricing', 'What it costs.', Group.PRODUCT, in_nav=True),
    Page('security', 'Security', 'How mail and the console are protected.', Group.PRODUCT, True),
    Page('docs', 'Documentation', 'Install and operate guides.', Group.RESOURCES, True),
    Page('changelog', 'Changelog', 'Release notes.', Group.PRODUCT, True, about_project=True),
    Page('download', 'Android app', 'The mobile app download.', Group.PRODUCT, True),
    Page('about', 'About', 'Who is behind it.', Group.PROJECT, about_project=True),
    Page('contact', 'Contact', 'How to reach you.', Group.PROJECT),
    Page('terms', 'Terms', 'Terms of service.', Group.LEGAL),
    Page('privacy', 'Privacy', 'Privacy policy.', Group.LEGAL),
)
BY_KEY = {p.key: p for p in PAGES}
KEYS = tuple(p.key for p in PAGES)

# Bounds on what an administrator may enter (also enforced where it is stored).
LIMITS = {
    'title': 120,
    'description': 300,
    'heading': 160,
    'lede': 400,
    'body': 20000,
    'cta_label': 40,
    'cta_url': 300,
}
TAGLINE_MAX = 160


class ContentError(ValueError):
    """Field-level problems; ``errors`` maps a field name to a message for the person editing."""

    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__('; '.join(f'{k}: {v}' for k, v in errors.items()))
        self.errors = errors
