"""What core.website registers at start-up.

The capability ``website.pages`` (the "Website pages" plugin's settings) and its in-console adapter
target. The target has no file for a container: publishing it stores the resolved policy in the
cache, so a public page costs one cache read instead of rendering every plugin.
"""

from __future__ import annotations

import json
import re

from backend.apps.core.plugins.services import registry
from backend.apps.core.plugins.services.registry import (
    AdapterTarget,
    Capability,
    CapabilityField,
    TargetKey,
)
from backend.apps.core.website.types import CAPABILITY, KEYS, MODES, TAGLINE_MAX, TARGET

_CONTROL = re.compile(r'[\x00-\x1f\x7f]')


def _modes(value: str) -> str | None:
    seen: set[str] = set()
    for item in value.split(','):
        page, _, mode = item.partition('=')
        if page not in KEYS:
            return f'unknown page: {page or item}'
        if mode not in MODES:
            return f'{page}: mode must be one of {", ".join(MODES)}'
        if page in seen:
            return f'{page} is listed twice'
        seen.add(page)
    return None


def _normalize_modes(value: str) -> str:
    pairs = {}
    for item in value.split(','):
        page, _, mode = item.strip().lower().partition('=')
        if page:
            pairs[page] = mode
    return ','.join(f'{k}={pairs[k]}' for k in KEYS if k in pairs) or ','.join(sorted(pairs))


def _yes_no(value: str) -> str | None:
    return None if value in ('yes', 'no') else 'must be yes or no'


def _line(value: str) -> str | None:
    if len(value) > TAGLINE_MAX:
        return f'at most {TAGLINE_MAX} characters'
    return 'must be one line of plain text' if _CONTROL.search(value) else None


class WebsiteTarget(AdapterTarget):
    """Read by the public pages themselves; nothing for a container to apply."""

    key = TARGET
    service = 'api'
    in_process = True
    keys = {
        'modes': TargetKey(_modes, 'Per page: standard, custom or off.', _normalize_modes),
        'powered_by': TargetKey(_yes_no, 'Show "Powered by" in the footer.'),
        'project_links': TargetKey(_yes_no, 'Show links to the open-source project.'),
        'tagline': TargetKey(_line, 'Footer sentence under the name.'),
        'footer_note': TargetKey(_line, 'Replaces the "Powered by" line.'),
    }

    def publish(self, text: str) -> bool:
        """Keep the resolved policy where the public pages read it (no file)."""
        from backend.apps.core.website.services import policy

        values = {}
        for line in text.splitlines():
            if line.startswith('#') or ' = ' not in line:
                continue
            key, _, value = line.partition(' = ')
            values[key.strip()] = value.strip()
        policy.store(json.dumps(policy.from_values(values).as_dict()))
        return False


class WebsiteCapability(Capability):
    key = CAPABILITY
    title = 'Website pages'
    description = 'Which public pages are shown, whose words they use, and what the footer says.'
    fields = {
        'modes': CapabilityField(
            _modes,
            'Per page: standard (as shipped), custom (the administrator’s own text) or off.',
            (TARGET, 'modes'),
            normalize=_normalize_modes,
        ),
        'powered_by': CapabilityField(
            _yes_no, 'yes: the footer says what the platform is.', (TARGET, 'powered_by')
        ),
        'project_links': CapabilityField(
            _yes_no,
            'yes: links to the open-source project (source code, issues, releases).',
            (TARGET, 'project_links'),
        ),
        'tagline': CapabilityField(
            _line, 'The sentence under the name in the footer; empty keeps the standard one.',
            (TARGET, 'tagline'),
        ),
        'footer_note': CapabilityField(
            _line, 'Replaces the "Powered by" line of the footer; empty keeps it.',
            (TARGET, 'footer_note'),
        ),
    }


def register() -> None:
    registry.register_target(WebsiteTarget())
    registry.register_capability(WebsiteCapability())
