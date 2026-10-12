"""The Assistant's model connection, read from the Assistant plugin (capability assistant.model)."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from backend.apps.core.assistant.types import CAPABILITY, NotConfiguredError
from backend.apps.core.plugins.services import InstallationService
from backend.apps.core.plugins.services import secrets as plugin_secrets

DEFAULT_DAILY_TOKENS = 200_000


@dataclass(frozen=True)
class ModelSettings:
    base_url: str
    model: str
    # Plain, only in memory while a question runs; never in repr, logs or tracebacks.
    api_key: str = field(default='', repr=False)
    daily_tokens: int = DEFAULT_DAILY_TOKENS

    @property
    def host(self) -> str:
        return urlsplit(self.base_url).hostname or ''


def current(*, with_key: bool = False) -> ModelSettings | None:
    """The configured connection, or None when the plugin is off or has no endpoint yet."""
    values = InstallationService.capability_values(CAPABILITY)
    base_url = values.get('base_url', '').strip()
    model = values.get('model', '').strip()
    if not base_url or not model:
        return None
    api_key = ''
    stored = values.get('api_key', '')
    if with_key and stored:
        try:
            api_key = plugin_secrets.decrypt(stored)
        except ValueError as exc:
            raise NotConfiguredError(str(exc).capitalize() + '.') from None
    try:
        daily = int(values.get('daily_tokens') or DEFAULT_DAILY_TOKENS)
    except ValueError:
        daily = DEFAULT_DAILY_TOKENS
    return ModelSettings(base_url=base_url, model=model, api_key=api_key, daily_tokens=daily)


def require(*, with_key: bool = True) -> ModelSettings:
    settings = current(with_key=with_key)
    if settings is None:
        raise NotConfiguredError(
            'No model is connected. Open Marketplace → Assistant and set the API base URL and '
            'model.'
        )
    return settings
