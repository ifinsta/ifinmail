"""Typed, permission-checked tools the agent may call.

Apps register tools from ``assistant_handlers.py`` (called in ``AppConfig.ready()``); each tool
calls that app's services, so the agent goes through the same rules as the console. Tiers:

* ``read``: returns state. Runs when the model asks.
* ``propose``: returns a drafted change, validated but not applied; a person clicks Apply.

There is no tier that changes anything on the model's say-so.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from backend.apps.core.assistant.types import ToolTier

_TYPES = {'string': str, 'integer': int, 'boolean': bool, 'object': dict}


@dataclass(frozen=True)
class ToolContext:
    user: str  # the administrator the agent works for


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    handler: Callable[[dict, ToolContext], object]
    tier: ToolTier = ToolTier.READ
    # JSON Schema properties: {name: {"type": ..., "description": ..., "enum": [...]}}
    parameters: dict = field(default_factory=dict)
    required: tuple[str, ...] = ()

    def schema(self) -> dict:
        """The OpenAI tool definition."""
        return {
            'type': 'function',
            'function': {
                'name': self.name,
                'description': self.description,
                'parameters': {
                    'type': 'object',
                    'properties': self.parameters,
                    'required': list(self.required),
                    'additionalProperties': False,
                },
            },
        }

    def check_arguments(self, arguments: dict) -> str | None:
        """An error message when the model's arguments do not fit the schema."""
        unknown = sorted(set(arguments) - set(self.parameters))
        if unknown:
            return f'unknown argument(s): {", ".join(unknown)}'
        for name in self.required:
            if name not in arguments:
                return f'missing argument: {name}'
        for name, value in arguments.items():
            spec = self.parameters[name]
            expected = _TYPES.get(spec.get('type', 'string'), str)
            if not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
                return f'{name} must be a {spec.get("type", "string")}'
            if 'enum' in spec and value not in spec['enum']:
                return f'{name} must be one of: {", ".join(map(str, spec["enum"]))}'
        return None


_tools: dict[str, Tool] = {}


def register(tool: Tool) -> None:
    if not tool.name.replace('_', '').isalnum() or len(tool.name) > 60:
        raise ValueError(f'invalid tool name {tool.name!r}')
    _tools[tool.name] = tool


def get(name: str) -> Tool | None:
    return _tools.get(name)


def all_tools() -> list[Tool]:
    return [_tools[k] for k in sorted(_tools)]
