"""The assistant's tools for the public website: understand each page, then draft its text.

* ``website_overview``: every page with its job, audience, what is at stake, its layout, whether
  it is shown and whether the organisation has written text for it, and the rules of a Custom
  page (fields, limits, the Markdown that is allowed).
* ``website_page_text``: the page's standard text and outline, and any text already written.
* ``propose_website_page``: a drafted page (and optionally its mode). Validated with the editor's
  own rules and shown with an Apply button; nothing changes until a person applies it.

The assistant reads and drafts; it never publishes. The drafted text is stored escaped-on-render
like anything typed in the editor.
"""

from __future__ import annotations

import hashlib
import json
import re

from django.contrib.auth.models import AnonymousUser
from django.urls import reverse

from backend.apps.core.assistant.services import tools
from backend.apps.core.assistant.services.tools import Tool, ToolContext
from backend.apps.core.assistant.types import AssistantError, ToolTier
from backend.apps.core.website.services import content, guide, policy, starter
from backend.apps.core.website.types import BY_KEY, KEYS, LIMITS, PAGES, PLUGIN_ID, ContentError

KIND = 'website_page'
# A tool result may be 12000 characters in all (JSON-escaped): the text leaves room for the guide.
STANDARD_CHARS = 6500  # of a page's standard text sent to the model
SHOWN_CHARS = 220  # of a long value in the before/after table
FIELDS = tuple(LIMITS)
_HEADING = re.compile(r'(?m)^(#{2,3}) (.+)$')


def _plugin_row():
    from backend.apps.core.plugins.services import InstallationService

    return InstallationService.get(PLUGIN_ID)


def _brand_name() -> str:
    from django.conf import settings

    brand = getattr(settings, 'BRAND_CONFIG', None)
    return str(getattr(brand, 'name', '') or '')


def _request():
    """A visitor's request, with this server's own address (the standard text quotes it)."""
    from django.test import RequestFactory

    from backend.config import site_url

    host = site_url.canonical_host() or 'localhost'
    request = RequestFactory().get('/', HTTP_HOST=host, secure=True)
    request.user = AnonymousUser()
    return request


def _digest(values: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def _short(value: str) -> str:
    value = value.strip()
    if not value:
        return ''
    flat = ' '.join(value.split())
    return flat if len(flat) <= SHOWN_CHARS else f'{flat[:SHOWN_CHARS]}… ({len(value)} characters)'


# ------------------------------------------------------------------------------------ read


def _overview(arguments: dict, context: ToolContext) -> dict:
    current = policy.current()
    written = content.has_text()
    row = _plugin_row()
    pages = []
    for page in PAGES:
        g = guide.for_page(page.key)
        pages.append(
            {
                'page': page.key,
                'name': page.label,
                'address': reverse(page.key),
                'mode': current.mode(page.key),
                'has_custom_text': page.key in written,
                'about_the_open_source_project': page.about_project,
                **({'risk': g.risk, 'purpose': g.purpose, 'usually': g.typical} if g else {}),
            }
        )
    return {
        'organisation_name_shown_in_header': _brand_name(),
        'plugin_installed': row is not None,
        'modes': {
            'standard': 'the page as shipped (written for the open-source project)',
            'custom': 'the organisation\'s own text from this tool, in the same layout',
            'off': 'not served: 404, or sign-in for the home page; removed from every menu',
        },
        'footer': {
            'powered_by_line_shown': current.powered_by,
            'project_links_shown': current.project_links,
            'tagline': current.tagline,
            'footer_note': current.footer_note,
            'how_to_change': 'propose_plugin_settings for plugin "website-pages" '
            '(powered_by, project_links, tagline, footer_note, mode_<page>)',
        },
        'custom_page_layout': guide.CUSTOM_LAYOUT,
        'limits_in_characters': dict(LIMITS),
        'pages': pages,
        'page': 'Settings → Website',
    }


def _page_text(arguments: dict, context: ToolContext) -> dict:
    key = arguments['page']
    from backend.config import public_pages

    try:
        start = starter.convert(public_pages.standard_html(_request(), key))
    except Exception as exc:  # a page that cannot render is reported, not fatal
        return {'error': f'the standard text of {key} could not be read ({type(exc).__name__})'}
    body = start.body
    outline = [m.group(2).strip() for m in _HEADING.finditer(body)]
    saved = content.get(key)
    g = guide.for_page(key)
    return {
        'page': key,
        'address': reverse(key),
        'mode': policy.current().mode(key),
        'standard': {
            'tab_title': start.title,
            'search_description': start.description,
            'heading': start.heading,
            'introduction': start.lede,
            'outline': outline,
            'text': body[:STANDARD_CHARS],
            'truncated': len(body) > STANDARD_CHARS,
        },
        'saved_custom_text': saved.as_dict() if saved.usable else None,
        **(
            {
                'purpose': g.purpose,
                'audience': g.audience,
                'standard_layout': g.layout,
                'at_stake': g.stakes,
                'risk': g.risk,
                'a_good_custom_version': g.write,
                'what_organisations_usually_do': g.typical,
                'body_length_in_words': g.body_words,
            }
            if g
            else {}
        ),
    }


# --------------------------------------------------------------------------------- propose


def _propose(arguments: dict, context: ToolContext) -> dict:
    key = arguments['page']
    mode = arguments.get('mode', '')
    page = BY_KEY[key]
    saved = content.get(key).as_dict()
    wanted = {name: str(arguments[name]) for name in FIELDS if name in arguments}
    merged = {**saved, **wanted}
    try:
        cleaned = content.clean(merged).as_dict()
    except ContentError as exc:
        return {'error': 'the draft is not valid', 'problems': exc.errors}
    if not (cleaned['heading'].strip() or cleaned['body'].strip()):
        return {'error': 'a page needs at least a heading or some text'}
    changes = [
        {'setting': name.replace('_', ' ').capitalize(), 'before': _short(saved[name]), 'after': _short(cleaned[name])}
        for name in FIELDS
        if cleaned[name] != saved[name]
    ]
    current_mode = policy.current().mode(key)
    row = _plugin_row()
    if mode and mode != current_mode:
        changes.append({'setting': 'Visitors see', 'before': current_mode, 'after': mode})
    if not changes:
        return {'result': 'these values are already in place; nothing to change'}
    proposal = {
        'kind': KIND,
        'page': key,
        'plugin_name': f'Website page: {page.label}',
        'installed': row is not None or not mode,
        'content': cleaned,
        'base': _digest(saved),
        'mode': mode if mode and mode != current_mode else '',
        'changes': changes,
    }
    note = (
        ''
        if mode == 'custom' or current_mode == 'custom'
        else f' The page keeps showing its {current_mode} version until its mode is Custom.'
    )
    return {
        'proposal': proposal,
        'result': 'drafted and validated; the administrator sees it with an Apply button.' + note,
        'changes': changes,
    }


def _apply(proposal: dict, user: str) -> str:
    """Click on Apply: re-check, then save the text and, when asked, switch the page's mode."""
    from backend.apps.core.plugins.services import InstallationService

    key = proposal.get('page', '')
    if key not in BY_KEY:
        raise AssistantError('That page no longer exists.')
    try:
        cleaned = content.clean(proposal.get('content') or {}).as_dict()
    except ContentError as exc:
        raise AssistantError(f'The draft no longer validates: {exc}') from None
    if _digest(content.get(key).as_dict()) != proposal.get('base'):
        raise AssistantError(
            'The text of this page changed since this draft was made. Nothing was changed; '
            'ask for a fresh draft.'
        )
    content.save(key, cleaned, user)
    mode = proposal.get('mode') or ''
    label = BY_KEY[key].label
    if not mode:
        shown = policy.current().mode(key)
        tail = '' if shown == 'custom' else f' It is not shown to visitors until its mode is Custom.'
        return f'Text for the {label} page saved.{tail}'
    setting = {f'mode_{key}': mode}
    if InstallationService.get(PLUGIN_ID) is None:
        InstallationService.install(PLUGIN_ID, setting, user)
    else:
        InstallationService.configure(PLUGIN_ID, setting, user)
    return f'Text for the {label} page saved and the page is now {mode}.'


def register() -> None:
    tools.register(
        Tool(
            'website_overview',
            'The public website: every page with its job, risk, current mode and whether the '
            'organisation has written text, the footer settings, and the rules of a custom '
            'page. Call first for anything about branding or changing the website; then call '
            'website_page_text for each page you will draft (it has the audience, layout and '
            'what is at stake).',
            _overview,
        )
    )
    tools.register(
        Tool(
            'website_page_text',
            'One public page: its audience, layout and what is at stake, its standard text as '
            'Markdown with its outline, and any custom text already saved. Call before drafting '
            'a page so the draft keeps what is accurate and drops what is about the '
            'open-source project.',
            _page_text,
            parameters={'page': {'type': 'string', 'enum': list(KEYS)}},
            required=('page',),
        )
    )
    tools.register(
        Tool(
            'propose_website_page',
            'Draft the organisation\'s own text for one public page. Validated with the '
            'editor\'s rules and shown to the administrator with an Apply button; changes '
            'nothing by itself. Fields you leave out keep their saved value. Set mode to '
            '"custom" so the text is shown, or "off" to remove the page. Use '
            'propose_plugin_settings (plugin website-pages) for the footer and project links.',
            _propose,
            tier=ToolTier.PROPOSE,
            parameters={
                'page': {'type': 'string', 'enum': list(KEYS)},
                'heading': {'type': 'string', 'description': 'the page heading, one line'},
                'lede': {'type': 'string', 'description': 'introduction, one or two sentences'},
                'body': {'type': 'string', 'description': 'Markdown body (see custom_page_layout)'},
                'cta_label': {'type': 'string', 'description': 'button text, with cta_url'},
                'cta_url': {
                    'type': 'string',
                    'description': 'https:// address, mailto: link, or a path on this site '
                    '(the address of a page from website_overview)',
                },
                'title': {'type': 'string', 'description': 'browser tab title'},
                'description': {'type': 'string', 'description': 'search description'},
                'mode': {'type': 'string', 'enum': ['standard', 'custom', 'off']},
            },
            required=('page',),
        )
    )
    tools.register_applier(KIND, _apply)
