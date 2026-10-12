"""What core.assistant registers at start-up.

* The capability ``assistant.model`` (the Assistant plugin's settings) and its in-console adapter
  target: the API key stays encrypted in the database and never reaches a runtime file.
* Core tools: an overview of plugins and their settings, recent audit events, and drafting plugin
  settings for the administrator to apply (propose tier).
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from backend.apps.core.assistant.services import tools
from backend.apps.core.assistant.services.tools import Tool, ToolContext
from backend.apps.core.assistant.types import CAPABILITY, AssistantError, ToolTier
from backend.apps.core.plugins.services import registry
from backend.apps.core.plugins.services import secrets as plugin_secrets
from backend.apps.core.plugins.services.registry import (
    AdapterTarget,
    Capability,
    CapabilityField,
    TargetKey,
)

ASSISTANT_PLUGIN = 'assistant'
_MODEL_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,119}$')


def _base_url(value: str) -> str | None:
    parts = urlsplit(value)
    if parts.scheme not in ('http', 'https') or not parts.hostname:
        return 'must be an http(s) URL, for example https://api.openai.com/v1'
    if parts.username or parts.password or parts.query or parts.fragment or len(value) > 300:
        return 'must be a plain base URL (no credentials, query or fragment)'
    return None


def _model(value: str) -> str | None:
    return None if _MODEL_RE.match(value) else 'must be a model name such as gpt-4o-mini'


def _encrypted(value: str) -> str | None:
    return None if plugin_secrets.is_encrypted(value) else 'must be stored encrypted'


def _tokens(value: str) -> str | None:
    ok = value.isdigit() and 1000 <= int(value) <= 10_000_000
    return None if ok else 'must be a whole number from 1000 to 10000000'


class AssistantTarget(AdapterTarget):
    """Read in the console by the assistant itself; no file, nothing for a container to apply."""

    key = 'console.assistant'
    service = 'api'
    in_process = True
    keys = {
        'base_url': TargetKey(_base_url, 'Model API base URL'),
        'model': TargetKey(_model, 'Model name'),
        'api_key': TargetKey(_encrypted, 'API key (encrypted)'),
        'daily_tokens': TargetKey(_tokens, 'Daily token budget'),
    }


class AssistantCapability(Capability):
    key = CAPABILITY
    title = 'Assistant model'
    description = 'The model the administrator assistant talks to (any OpenAI-compatible API).'
    fields = {
        'base_url': CapabilityField(
            _base_url,
            'API base URL of an OpenAI-compatible endpoint; empty leaves the assistant off.',
            ('console.assistant', 'base_url'),
            normalize=lambda v: v.strip().rstrip('/'),
        ),
        'model': CapabilityField(_model, 'Model name.', ('console.assistant', 'model')),
        'api_key': CapabilityField(
            _encrypted,
            'API key, stored encrypted and sent only to the API host.',
            ('console.assistant', 'api_key'),
            secret=True,
        ),
        'daily_tokens': CapabilityField(
            _tokens,
            'Most tokens the assistant may use per day.',
            ('console.assistant', 'daily_tokens'),
        ),
    }


# ------------------------------------------------------------------------------ tools


def _display(spec, value: object) -> object:  # noqa: ANN001
    if spec.type == 'secret':
        return plugin_secrets.MASK if value else ''
    return value


def _plugins_overview(arguments: dict, context: ToolContext) -> dict:
    from backend.apps.core.plugins.services import CatalogService, InstallationService

    out = []
    for entry in CatalogService.entries():
        manifest = entry.manifest
        row = InstallationService.get(entry.plugin_id)
        out.append(
            {
                'plugin_id': entry.plugin_id,
                'name': manifest.name,
                'summary': manifest.summary,
                'installed': row.state if row else 'not installed',
                'capabilities': sorted(manifest.capability_keys()),
                'settings': [
                    {
                        'key': spec.key,
                        'label': spec.label,
                        'type': spec.type,
                        'help': spec.help,
                        **({'options': list(spec.options)} if spec.options else {}),
                        **({'min': spec.min} if spec.min is not None else {}),
                        **({'max': spec.max} if spec.max is not None else {}),
                        'default': _display(spec, spec.default),
                        **({'current': _display(spec, row.settings.get(spec.key))} if row else {}),
                    }
                    for spec in manifest.settings
                ],
            }
        )
    return {'plugins': out, 'page': 'Marketplace'}


def _audit_recent(arguments: dict, context: ToolContext) -> dict:
    from backend.apps.core.platform.services.audit import AuditService

    limit = max(1, min(int(arguments.get('limit', 20)), 50))
    needle = str(arguments.get('action_contains', '')).lower()
    events = [
        e for e in AuditService.get_recent(200) if not needle or needle in str(e.get('action', ''))
    ]
    return {'events': events[-limit:], 'page': 'System Logs'}


def _propose_plugin_settings(arguments: dict, context: ToolContext) -> dict:
    from backend.apps.core.plugins.services import CatalogService, InstallationService
    from backend.apps.core.plugins.services import manifest as manifests
    from backend.apps.core.plugins.types import PluginError, SettingsError

    plugin_id = str(arguments.get('plugin_id', ''))
    wanted = arguments.get('settings') or {}
    if plugin_id == ASSISTANT_PLUGIN:
        raise AssistantError('The assistant cannot change its own connection settings.')
    entry = CatalogService.get(plugin_id)
    if entry is None:
        raise AssistantError(f'No plugin "{plugin_id}"; call plugins_overview for the ids.')
    row = InstallationService.get(plugin_id)
    manifest = InstallationService.manifest_of(row) if row else entry.manifest
    specs = {spec.key: spec for spec in manifest.settings}
    unknown = sorted(set(wanted) - set(specs))
    if unknown:
        raise AssistantError(f'{plugin_id} has no setting(s) {", ".join(unknown)}.')
    if any(specs[k].type == 'secret' for k in wanted):
        raise AssistantError('Secrets are entered by the administrator, never drafted.')
    current = dict(row.settings) if row else {}
    try:
        try:
            before = manifests.clean_settings(manifest, current, live=False)
        except SettingsError:
            before = {}  # not installed and has required settings: nothing set before
        after = manifests.clean_settings(manifest, {**current, **wanted})
        manifests.rendered_values(manifest, after)
    except SettingsError as exc:
        return {'error': 'the draft is not valid', 'problems': exc.errors}
    except PluginError as exc:
        return {'error': str(exc)}

    def shown(value: object) -> object:
        return {True: 'on', False: 'off'}.get(value, value) if isinstance(value, bool) else value

    changes = [
        {
            'setting': specs[k].label,
            'key': k,
            'before': shown(before.get(k)),
            'after': shown(after.get(k)),
        }
        for k in sorted(wanted)
        if before.get(k) != after.get(k)
    ]
    if not changes and row:
        return {'result': 'these values are already in effect; nothing to change'}
    proposal = {
        'plugin_id': plugin_id,
        'plugin_name': manifest.name,
        'installed': bool(row),
        'settings': {k: after.get(k) for k in wanted},
        'changes': changes,
    }
    return {
        'proposal': proposal,
        'result': 'drafted and validated; the administrator sees it with an Apply button'
        + ('' if row else ' (applying also installs the plugin)'),
        'changes': changes,
    }


def register() -> None:
    registry.register_target(AssistantTarget())
    registry.register_capability(AssistantCapability())
    tools.register(
        Tool(
            'plugins_overview',
            'Every available plugin: what it does, whether it is installed, and each setting with '
            'its type, limits, default and current value. Call before drafting plugin settings.',
            _plugins_overview,
        )
    )
    tools.register(
        Tool(
            'audit_recent',
            'Recent audit events (sign-ins, changes, plugin operations), newest last.',
            _audit_recent,
            parameters={
                'limit': {'type': 'integer', 'description': '1-50, default 20'},
                'action_contains': {
                    'type': 'string',
                    'description': 'only events whose action contains this text, e.g. login',
                },
            },
        )
    )
    tools.register(
        Tool(
            'propose_plugin_settings',
            'Draft new settings for one plugin. Validates them with the real rules and shows the '
            'administrator a before/after with an Apply button. Changes nothing by itself.',
            _propose_plugin_settings,
            tier=ToolTier.PROPOSE,
            parameters={
                'plugin_id': {'type': 'string', 'description': 'from plugins_overview'},
                'settings': {
                    'type': 'object',
                    'description': 'only the settings to change: {setting key: new value}',
                },
            },
            required=('plugin_id', 'settings'),
        )
    )
