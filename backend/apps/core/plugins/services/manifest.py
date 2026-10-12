"""Parse and validate plugin manifests (TOML, manifest_version 2), and validate settings.

Strict by design: unknown keys are errors, every problem is reported at once with its location,
and nothing in a manifest is ever executed. Parsing is cached by content hash, so the same text is
validated once per process.
"""

from __future__ import annotations

import hashlib
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from functools import lru_cache

from backend.apps.core.plugins.services import registry
from backend.apps.core.plugins.services import secrets as plugin_secrets
from backend.apps.core.plugins.types import (
    CATEGORIES,
    MANIFEST_VERSION,
    MAX_MANIFEST_BYTES,
    ManifestError,
    SettingsError,
)

ID_RE = re.compile(r'^[a-z][a-z0-9-]{2,39}$')
KEY_RE = re.compile(r'^[a-z][a-z0-9_]{0,39}$')
VERSION_RE = re.compile(r'^(0|[1-9]\d{0,3})\.(0|[1-9]\d{0,3})\.(0|[1-9]\d{0,3})$')
EMAIL_RE = re.compile(
    r'^[^\s@",;:<>()\[\]\\]{1,64}@[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?'
    r'(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$'
)
CONTROL_RE = re.compile(r'[\x00-\x1f\x7f]')
DESCRIPTION_CONTROL_RE = re.compile(r'[\x00-\x08\x0b-\x1f\x7f]')
PLACEHOLDER_RE = re.compile(r'\{\{|\}\}|\{([^{}]*)\}|[{}]')

BUILTIN_TYPES = ('text', 'integer', 'boolean', 'choice', 'email', 'secret')
MAX_SETTINGS = 20
MAX_CONTRIBUTIONS = 10
TRUE_WORDS = ('on', 'true', '1', 'yes')

_TOP_KEYS = {'manifest_version', 'plugin', 'settings', 'contributes'}
_PLUGIN_KEYS = {
    'id',
    'name',
    'version',
    'publisher',
    'category',
    'summary',
    'description',
    'requires_core',
    'install_by_default',
}
_SETTING_KEYS = {
    'key',
    'type',
    'label',
    'help',
    'required',
    'default',
    'min',
    'max',
    'options',
    'max_length',
}
_CONTRIB_KEYS = {'capability', 'values'}


def parse_version(text: str) -> tuple[int, int, int] | None:
    match = VERSION_RE.match(text or '')
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


@dataclass(frozen=True)
class SettingSpec:
    key: str
    type: str
    label: str
    help: str = ''
    required: bool = False
    default: object = None
    min: int | None = None
    max: int | None = None
    options: tuple[str, ...] = ()
    max_length: int = 200

    @property
    def base_type(self) -> str:
        if self.type in BUILTIN_TYPES:
            return self.type
        extra = registry.setting_type(self.type)
        return extra[0] if extra else self.type


@dataclass(frozen=True)
class Contribution:
    capability: str
    values: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class PluginManifest:
    id: str
    name: str
    version: str
    publisher: str
    category: str
    summary: str
    description: str
    requires_core: str
    settings: tuple[SettingSpec, ...]
    contributes: tuple[Contribution, ...]
    sha256: str
    text: str = field(repr=False)
    # Installed once on every server (bundled plugins only); an uninstall is respected.
    install_by_default: bool = False

    @property
    def version_tuple(self) -> tuple[int, int, int]:
        return parse_version(self.version) or (0, 0, 0)

    @property
    def paragraphs(self) -> list[str]:
        return [p.strip() for p in self.description.split('\n\n') if p.strip()]

    def setting(self, key: str) -> SettingSpec | None:
        return next((s for s in self.settings if s.key == key), None)

    def claimed_keys(self) -> set[tuple[str, str]]:
        """(capability, field) pairs this plugin writes; used for conflict detection."""
        return {(c.capability, k) for c in self.contributes for k, _ in c.values}

    def capability_keys(self) -> set[str]:
        return {c.capability for c in self.contributes}


# --------------------------------------------------------------------------------- parsing


def load(text: str | bytes) -> PluginManifest:
    """Parse and validate a manifest. Raises ``ManifestError`` listing every problem."""
    if isinstance(text, bytes):
        if len(text) > MAX_MANIFEST_BYTES:
            raise ManifestError([('manifest', f'is larger than {MAX_MANIFEST_BYTES // 1024} KiB')])
        try:
            text = text.decode('utf-8')
        except UnicodeDecodeError:
            raise ManifestError([('manifest', 'is not UTF-8 text')]) from None
    return _load_cached(text)


@lru_cache(maxsize=128)
def _load_cached(text: str) -> PluginManifest:
    if len(text.encode('utf-8')) > MAX_MANIFEST_BYTES:
        raise ManifestError([('manifest', f'is larger than {MAX_MANIFEST_BYTES // 1024} KiB')])
    clean = text.removeprefix('﻿')
    try:
        data = tomllib.loads(clean)
    except tomllib.TOMLDecodeError as exc:
        raise ManifestError([('manifest', f'is not valid TOML: {exc}')]) from None
    problems: list[tuple[str, str]] = []
    manifest = _validate(data, problems, text)
    if problems or manifest is None:
        raise ManifestError(problems or [('manifest', 'invalid')])
    return manifest


def _str(
    table: Mapping, key: str, where: str, problems: list, *, lo: int, hi: int, required: bool = True
) -> str:
    value = table.get(key)
    if value is None:
        if required:
            problems.append((f'{where}.{key}', 'is required'))
        return ''
    if not isinstance(value, str):
        problems.append((f'{where}.{key}', 'must be text'))
        return ''
    stripped = value.strip()
    # Descriptions may contain line breaks and tabs; nothing else may contain control characters.
    forbidden = DESCRIPTION_CONTROL_RE if key == 'description' else CONTROL_RE
    if forbidden.search(stripped):
        problems.append((f'{where}.{key}', 'must not contain control characters'))
    if not lo <= len(stripped) <= hi:
        problems.append((f'{where}.{key}', f'must be {lo}-{hi} characters'))
        return ''  # one problem per field: skip the format checks that follow
    return stripped


def _unknown(table: Mapping, allowed: set[str], where: str, problems: list) -> None:
    for key in sorted(set(table) - allowed):
        problems.append((f'{where}.{key}' if where else key, 'is not a recognised key'))


def _validate(data: Mapping, problems: list, text: str) -> PluginManifest | None:
    _unknown(data, _TOP_KEYS, '', problems)
    if data.get('manifest_version') == 1 and not isinstance(data.get('manifest_version'), bool):
        problems.append(
            (
                'manifest_version',
                f'1 named mail software directly; use {MANIFEST_VERSION}, where each '
                '[[contributes]] names a capability (e.g. capability = "mail.journal")',
            )
        )
    elif data.get('manifest_version') != MANIFEST_VERSION or isinstance(
        data.get('manifest_version'), bool
    ):
        problems.append(('manifest_version', f'must be {MANIFEST_VERSION}'))
    plugin = data.get('plugin')
    if not isinstance(plugin, dict):
        problems.append(('plugin', 'section is required'))
        return None
    _unknown(plugin, _PLUGIN_KEYS, 'plugin', problems)
    plugin_id = _str(plugin, 'id', 'plugin', problems, lo=3, hi=40)
    if plugin_id and (not ID_RE.match(plugin_id) or '--' in plugin_id or plugin_id.endswith('-')):
        problems.append(('plugin.id', 'must be lowercase letters, digits and single hyphens'))
    name = _str(plugin, 'name', 'plugin', problems, lo=1, hi=60)
    version = _str(plugin, 'version', 'plugin', problems, lo=5, hi=20)
    if version and not parse_version(version):
        problems.append(('plugin.version', 'must be MAJOR.MINOR.PATCH, e.g. 1.0.0'))
    publisher = _str(plugin, 'publisher', 'plugin', problems, lo=1, hi=60)
    category = _str(plugin, 'category', 'plugin', problems, lo=1, hi=20)
    if category and category not in CATEGORIES:
        problems.append(('plugin.category', f'must be one of: {", ".join(CATEGORIES)}'))
    summary = _str(plugin, 'summary', 'plugin', problems, lo=1, hi=160)
    description = _str(plugin, 'description', 'plugin', problems, lo=0, hi=4000, required=False)
    requires_core = _str(plugin, 'requires_core', 'plugin', problems, lo=5, hi=20, required=False)
    if requires_core and not parse_version(requires_core):
        problems.append(('plugin.requires_core', 'must be MAJOR.MINOR.PATCH, e.g. 0.0.4'))
    install_by_default = plugin.get('install_by_default', False)
    if not isinstance(install_by_default, bool):
        problems.append(('plugin.install_by_default', 'must be true or false'))
        install_by_default = False

    settings = _validate_settings(data.get('settings', []), problems)
    contributes = _validate_contributions(data.get('contributes'), settings, problems)
    if problems:
        return None
    return PluginManifest(
        id=plugin_id,
        name=name,
        version=version,
        publisher=publisher,
        category=category,
        summary=summary,
        description=description,
        requires_core=requires_core,
        settings=tuple(settings),
        contributes=tuple(contributes),
        sha256=hashlib.sha256(text.encode('utf-8')).hexdigest(),
        text=text,
        install_by_default=install_by_default,
    )


def _validate_settings(raw: object, problems: list) -> list[SettingSpec]:
    if not isinstance(raw, list):
        problems.append(('settings', 'must be a list of [[settings]] tables'))
        return []
    if len(raw) > MAX_SETTINGS:
        problems.append(('settings', f'at most {MAX_SETTINGS} settings'))
    specs: list[SettingSpec] = []
    seen: set[str] = set()
    for i, item in enumerate(raw):
        where = f'settings[{i}]'
        if not isinstance(item, dict):
            problems.append((where, 'must be a table'))
            continue
        _unknown(item, _SETTING_KEYS, where, problems)
        key = _str(item, 'key', where, problems, lo=1, hi=40)
        if key and not KEY_RE.match(key):
            problems.append((f'{where}.key', 'must be lowercase letters, digits and underscores'))
        if key in seen:
            problems.append((f'{where}.key', f'"{key}" is declared twice'))
        seen.add(key)
        kind = _str(item, 'type', where, problems, lo=1, hi=20)
        known = kind in BUILTIN_TYPES or registry.setting_type(kind) is not None
        if kind and not known:
            problems.append((f'{where}.type', f'unknown type "{kind}"'))
        label = _str(item, 'label', where, problems, lo=1, hi=60)
        help_text = _str(item, 'help', where, problems, lo=0, hi=300, required=False)
        required = item.get('required', False)
        if not isinstance(required, bool):
            problems.append((f'{where}.required', 'must be true or false'))
            required = False
        spec_kwargs: dict = {}
        base = kind if kind in BUILTIN_TYPES else (registry.setting_type(kind) or ('',))[0]
        for bound in ('min', 'max'):
            if bound in item:
                if base != 'integer' or not _is_int(item[bound]):
                    problems.append(
                        (f'{where}.{bound}', 'only integer settings take an integer bound')
                    )
                else:
                    spec_kwargs[bound] = item[bound]
        low, high = spec_kwargs.get('min'), spec_kwargs.get('max')
        if low is not None and high is not None and low > high:
            problems.append((f'{where}.min', 'is greater than max'))
        if 'options' in item:
            options = item['options']
            if base != 'choice':
                problems.append((f'{where}.options', 'only choice settings take options'))
            elif (
                not isinstance(options, list)
                or not 1 <= len(options) <= 50
                or not all(isinstance(o, str) and 1 <= len(o) <= 60 for o in options)
                or len(set(options)) != len(options)
            ):
                problems.append(
                    (f'{where}.options', 'must be 1-50 unique texts of 1-60 characters')
                )
            else:
                spec_kwargs['options'] = tuple(options)
        elif base == 'choice':
            problems.append((f'{where}.options', 'is required for a choice'))
        if 'max_length' in item:
            if (
                base not in ('text', 'secret')
                or not _is_int(item['max_length'])
                or not 1 <= item['max_length'] <= 500
            ):
                problems.append(
                    (f'{where}.max_length', 'only text and secret settings take max_length (1-500)')
                )
            else:
                spec_kwargs['max_length'] = item['max_length']
        spec = SettingSpec(
            key=key, type=kind, label=label, help=help_text, required=required, **spec_kwargs
        )
        if 'default' in item:
            if kind == 'secret':
                problems.append((f'{where}.default', 'secret settings cannot have a default'))
            elif registry.setting_type(kind) is not None:
                problems.append((f'{where}.default', f'"{kind}" settings cannot have a default'))
            elif known:
                try:
                    spec = replace(spec, default=_clean_value(spec, item['default'], live=False))
                except ValueError as exc:
                    problems.append((f'{where}.default', str(exc)))
        specs.append(spec)
    return specs


def _validate_contributions(
    raw: object, settings: list[SettingSpec], problems: list
) -> list[Contribution]:
    if not isinstance(raw, list) or not raw:
        problems.append(('contributes', 'at least one [[contributes]] entry is required'))
        return []
    if len(raw) > MAX_CONTRIBUTIONS:
        problems.append(('contributes', f'at most {MAX_CONTRIBUTIONS} entries'))
    declared = {s.key for s in settings}
    secret_keys = {s.key for s in settings if s.type == 'secret'}
    claimed: set[tuple[str, str]] = set()
    result: list[Contribution] = []
    for i, item in enumerate(raw):
        where = f'contributes[{i}]'
        if not isinstance(item, dict):
            problems.append((where, 'must be a table'))
            continue
        _unknown(item, _CONTRIB_KEYS, where, problems)
        cap_key = item.get('capability')
        capability = registry.get_capability(cap_key) if isinstance(cap_key, str) else None
        if capability is None:
            problems.append(
                (f'{where}.capability', f'"{cap_key}" is not a capability this server offers')
            )
        values = item.get('values')
        if not isinstance(values, dict) or not values:
            problems.append((f'{where}.values', 'must be a non-empty table of text values'))
            continue
        pairs: list[tuple[str, str]] = []
        for key, template in values.items():
            loc = f'{where}.values.{key}'
            if not isinstance(template, str):
                problems.append((loc, 'must be text'))
                continue
            if capability is not None and key not in capability.fields:
                problems.append((loc, f'is not a field of {capability.key}'))
            if (cap_key, key) in claimed:
                problems.append((loc, 'is set twice in this manifest'))
            claimed.add((cap_key, key))
            try:
                names = placeholders(template)
            except ValueError as exc:
                problems.append((loc, str(exc)))
                continue
            for name in names:
                if name not in declared:
                    problems.append((loc, f'refers to undeclared setting "{name}"'))
            field_spec = capability.fields.get(key) if capability is not None else None
            is_secret_field = bool(field_spec and field_spec.secret)
            whole = len(names) == 1 and template == '{' + names[0] + '}'
            if secret_keys & set(names) and not (whole and is_secret_field):
                # A secret may only travel whole, to a field that keeps it inside the console.
                problems.append((loc, 'a secret setting may only be a secret field, whole'))
            if is_secret_field and not (len(names) == 1 and names[0] in secret_keys):
                problems.append((loc, 'a secret field takes exactly one secret setting'))
            if capability is not None and key in capability.fields and not names:
                # A literal value: check it now rather than at install time.
                error = capability.validate(key, capability.normalize(key, template))
                if error:
                    problems.append((loc, error))
            pairs.append((key, template))
        result.append(Contribution(capability=str(cap_key), values=tuple(pairs)))
    return result


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


# --------------------------------------------------------------------------------- templates


def placeholders(template: str) -> list[str]:
    """Setting names referenced by ``{name}``; ``{{``/``}}`` are literal braces."""
    names: list[str] = []
    for match in PLACEHOLDER_RE.finditer(template):
        token = match.group(0)
        if token in ('{{', '}}'):
            continue
        if token in ('{', '}'):
            raise ValueError('has an unmatched brace (write {{ or }} for a literal brace)')
        name = match.group(1)
        if not KEY_RE.match(name or ''):
            raise ValueError(f'has an invalid placeholder "{{{name}}}"')
        names.append(name)
    return names


def expand(template: str, values: Mapping[str, object]) -> str:
    def replace(match: re.Match) -> str:
        token = match.group(0)
        if token == '{{':
            return '{'
        if token == '}}':
            return '}'
        value = values.get(match.group(1))
        if value is None:
            return ''
        if isinstance(value, bool):
            return 'yes' if value else 'no'
        return str(value)

    return PLACEHOLDER_RE.sub(replace, template)


# --------------------------------------------------------------------------------- settings


def _clean_value(spec: SettingSpec, raw: object, *, live: bool) -> object:
    """Normalise one setting value or raise ValueError with a user-facing message."""
    base = spec.base_type
    if base == 'boolean':
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in TRUE_WORDS
    if raw is None or (isinstance(raw, str) and raw.strip() == ''):
        if spec.required:
            raise ValueError('is required')
        return None
    if base == 'secret':
        if plugin_secrets.is_encrypted(raw):
            return raw  # already stored; never decrypted here
        if not isinstance(raw, str):
            raise ValueError('must be text')
        text = raw.strip()
        if CONTROL_RE.search(text) or ' ' in text:
            raise ValueError('must not contain spaces or control characters')
        if len(text) > spec.max_length:
            raise ValueError(f'must be at most {spec.max_length} characters')
        return plugin_secrets.encrypt(text)
    if base == 'integer':
        if isinstance(raw, bool):
            raise ValueError('must be a whole number')
        try:
            value = int(str(raw).strip())
        except ValueError:
            raise ValueError('must be a whole number') from None
        if spec.min is not None and value < spec.min:
            raise ValueError(f'must be at least {spec.min}')
        if spec.max is not None and value > spec.max:
            raise ValueError(f'must be at most {spec.max}')
        return value
    if not isinstance(raw, str | int | float) or isinstance(raw, bool):
        raise ValueError('must be text')
    text = str(raw).strip()
    if CONTROL_RE.search(text):
        raise ValueError('must not contain control characters')
    if base == 'choice':
        if text not in spec.options:
            raise ValueError(f'must be one of: {", ".join(spec.options)}')
        return text
    if base == 'email':
        text = text.lower()
        if len(text) > 254 or not EMAIL_RE.match(text):
            raise ValueError('must be a single email address')
        extra = registry.setting_type(spec.type)
        if live and extra is not None:
            error = extra[1](text)
            if error:
                raise ValueError(error)
        return text
    if len(text) > spec.max_length:
        raise ValueError(f'must be at most {spec.max_length} characters')
    return text


def clean_settings(
    manifest: PluginManifest, raw: Mapping[str, object], *, live: bool = True
) -> dict[str, object]:
    """Validate submitted values against the manifest. Values not supplied take their default.

    Keys the manifest does not declare are dropped (forms carry other fields such as the CSRF
    token). Raises ``SettingsError`` mapping each bad key to its message.
    """
    cleaned: dict[str, object] = {}
    errors: dict[str, str] = {}
    for spec in manifest.settings:
        value = raw.get(spec.key)
        # A default applies only when the value is not supplied at all. Forms show the default
        # and always post every field, so what the administrator sees is what is saved: a field
        # cleared on purpose stays empty, and an unchecked checkbox (posted empty) means false.
        if value is None and spec.default is not None:
            value = spec.default
        try:
            cleaned[spec.key] = _clean_value(spec, value, live=live)
        except ValueError as exc:
            errors[spec.key] = str(exc)
    if errors:
        raise SettingsError(errors)
    return cleaned


def rendered_values(
    manifest: PluginManifest, settings: Mapping[str, object]
) -> dict[str, dict[str, str]]:
    """``{capability: {field: value}}`` after expansion, validated by each capability's grammar
    and checked to be expressible by the engine adapters (``registry.to_targets``)."""
    out: dict[str, dict[str, str]] = {}
    problems: dict[str, str] = {}
    for contribution in manifest.contributes:
        capability = registry.get_capability(contribution.capability)
        for key, template in contribution.values:
            value = expand(template, settings).strip()
            where = f'{contribution.capability}.{key}'
            if capability is None:
                problems[where] = 'this server does not offer the capability'
                continue
            value = capability.normalize(key, value)
            error = capability.validate(key, value)
            if error:
                problems[where] = error
            out.setdefault(contribution.capability, {})[key] = value
    if not problems:
        try:
            registry.to_targets(out)
        except ValueError as exc:
            problems['manifest'] = str(exc)
    if problems:
        raise SettingsError(problems)
    return out
