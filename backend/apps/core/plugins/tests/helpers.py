"""Test helpers: build manifests as data, write them as TOML."""

from __future__ import annotations

import copy
import json


def _value(value: object) -> str:
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        return '[' + ', '.join(_value(v) for v in value) + ']'
    if isinstance(value, dict):
        return '{ ' + ', '.join(f'{_key(k)} = {_value(v)}' for k, v in value.items()) + ' }'
    raise TypeError(type(value))


def _key(key: str) -> str:
    return key if key.replace('_', '').replace('-', '').isalnum() else json.dumps(key)


def to_toml(data: dict) -> str:
    lines: list[str] = []
    tables = {k: v for k, v in data.items() if isinstance(v, dict)}
    arrays = {k: v for k, v in data.items() if isinstance(v, list) and v and isinstance(v[0], dict)}
    for key, value in data.items():
        if key not in tables and key not in arrays:
            lines.append(f'{_key(key)} = {_value(value)}')
    for name, table in tables.items():
        lines.append(f'\n[{name}]')
        lines += [f'{_key(k)} = {_value(v)}' for k, v in table.items()]
    for name, items in arrays.items():
        for item in items:
            lines.append(f'\n[[{name}]]')
            lines += [f'{_key(k)} = {_value(v)}' for k, v in item.items()]
    return '\n'.join(lines) + '\n'


BASE = {
    'manifest_version': 2,
    'plugin': {
        'id': 'test-journal',
        'name': 'Test journal',
        'version': '1.0.0',
        'publisher': 'Example',
        'category': 'compliance',
        'summary': 'Copies mail.',
        'description': 'First paragraph.\n\nSecond paragraph.',
    },
    'settings': [
        {'key': 'archive_address', 'type': 'mailbox', 'label': 'Archive', 'required': True},
    ],
    'contributes': [
        {'capability': 'mail.journal', 'values': {'archive_address': '{archive_address}'}},
    ],
}


def manifest(**changes: object) -> dict:
    """A copy of BASE; ``plugin__x=...`` changes plugin.x, ``settings=...`` replaces a list."""
    data = copy.deepcopy(BASE)
    for key, value in changes.items():
        if key.startswith('plugin__'):
            name = key.removeprefix('plugin__')
            if value is None:
                data['plugin'].pop(name, None)
            else:
                data['plugin'][name] = value
        elif value is None:
            data.pop(key, None)
        else:
            data[key] = value
    return data


def text(**changes: object) -> str:
    return to_toml(manifest(**changes))
