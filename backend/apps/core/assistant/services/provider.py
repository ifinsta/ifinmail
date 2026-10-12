"""Model providers. One interface; the OpenAI-compatible chat-completions API is the first one.

``POST {base_url}/chat/completions`` with ``tools`` (function calling) is spoken by OpenAI,
Anthropic's compatibility endpoint, OpenRouter, Groq, Mistral, DeepSeek, Together, Ollama, vLLM,
LM Studio and LiteLLM. Other API styles can be added as further ``ChatProvider`` classes.

Safety: the API key is sent only to the configured host (redirects are refused), TLS is verified,
and cloud metadata addresses are refused. Private addresses are allowed for local models.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import time
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlsplit

import requests

from backend.apps.core.assistant.types import (
    CALL_TIMEOUT_SECONDS,
    CONNECT_TIMEOUT_SECONDS,
    ProviderError,
)

_BLOCKED_NETWORKS = (
    ipaddress.ip_network('169.254.0.0/16'),  # link-local, incl. cloud metadata 169.254.169.254
    ipaddress.ip_network('fe80::/10'),
    ipaddress.ip_network('fd00:ec2::/32'),  # AWS IPv6 metadata
    ipaddress.ip_network('0.0.0.0/8'),
)
_BLOCKED_HOSTS = {'metadata.google.internal', 'metadata'}
RETRY_DELAY_SECONDS = 2.0


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass(frozen=True)
class ChatResult:
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    tokens: int = 0
    raw_tool_calls: list = field(default_factory=list)  # as the API sent them, for the history


class ChatProvider(Protocol):
    host: str

    def complete(self, messages: list[dict], tools: list[dict]) -> ChatResult: ...


def check_endpoint(base_url: str) -> str:
    """Validate the base URL and the address it resolves to. Returns the host."""
    parts = urlsplit(base_url)
    if parts.scheme not in ('http', 'https') or not parts.hostname:
        raise ProviderError(
            'The API base URL must start with https:// (or http:// on your network).'
        )
    if parts.username or parts.password:
        raise ProviderError('Put the API key in its own field, not in the URL.')
    host = parts.hostname.lower()
    if host in _BLOCKED_HOSTS:
        raise ProviderError('That address is a cloud metadata service and is not allowed.')
    try:
        infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == 'https' else 80))
    except OSError:
        raise ProviderError(f'{host} could not be resolved.') from None
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if any(address in net for net in _BLOCKED_NETWORKS):
            raise ProviderError(f'{host} resolves to {address}, which is not allowed.')
    return host


class OpenAICompatibleProvider:
    def __init__(self, base_url: str, model: str, api_key: str = '') -> None:
        self.base_url = base_url.rstrip('/')
        self.model = model
        self._api_key = api_key
        self.host = urlsplit(base_url).hostname or ''

    def __repr__(self) -> str:  # never the key
        return f'OpenAICompatibleProvider({self.base_url!r}, {self.model!r})'

    def complete(self, messages: list[dict], tools: list[dict]) -> ChatResult:
        check_endpoint(self.base_url)
        body: dict = {'model': self.model, 'messages': messages, 'temperature': 0.2}
        if tools:
            body['tools'] = tools
            body['tool_choice'] = 'auto'
        headers = {'Content-Type': 'application/json'}
        if self._api_key:
            headers['Authorization'] = f'Bearer {self._api_key}'
        response = self._post(f'{self.base_url}/chat/completions', body, headers)
        return self._parse(response, sent_chars=len(json.dumps(body)))

    def _post(self, url: str, body: dict, headers: dict) -> requests.Response:
        last: Exception | None = None
        for attempt in range(2):
            try:
                response = requests.post(
                    url,
                    json=body,
                    headers=headers,
                    timeout=(CONNECT_TIMEOUT_SECONDS, CALL_TIMEOUT_SECONDS),
                    allow_redirects=False,
                )
            except requests.RequestException as exc:
                last = exc
            else:
                if response.status_code == 429 or response.status_code >= 500:
                    last = ProviderError(self._error_text(response))
                else:
                    return response
            if attempt == 0:
                time.sleep(RETRY_DELAY_SECONDS)
        if isinstance(last, ProviderError):
            raise last
        raise ProviderError(f'{self.host} could not be reached ({type(last).__name__}).')

    def _error_text(self, response: requests.Response) -> str:
        code = response.status_code
        detail = ''
        try:
            payload = response.json()
            error = payload.get('error', payload) if isinstance(payload, dict) else {}
            detail = str(error.get('message', '') if isinstance(error, dict) else error)[:300]
        except ValueError:
            pass
        if 300 <= code < 400:
            return f'{self.host} answered with a redirect; use the final API base URL instead.'
        reason = {
            401: 'the API key was refused',
            403: 'the API key may not use this model',
            404: 'the URL or model was not found (the base URL usually ends in /v1)',
            429: 'too many requests or quota exhausted at the provider',
        }.get(code, f'HTTP {code}')
        return f'{self.host}: {reason}' + (f' ({detail})' if detail else '') + '.'

    def _parse(self, response: requests.Response, sent_chars: int = 0) -> ChatResult:
        if response.status_code != 200:
            raise ProviderError(self._error_text(response))
        try:
            payload = response.json()
            message = payload['choices'][0]['message']
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError(
                f'{self.host} did not answer in the chat-completions format.'
            ) from None
        raw_calls = message.get('tool_calls') or []
        calls: list[ToolCall] = []
        for raw in raw_calls:
            function = raw.get('function') or {}
            try:
                arguments = json.loads(function.get('arguments') or '{}')
            except (TypeError, ValueError):
                arguments = {'_invalid': str(function.get('arguments'))[:200]}
            if not isinstance(arguments, dict):
                arguments = {'_invalid': str(arguments)[:200]}
            calls.append(
                ToolCall(str(raw.get('id') or ''), str(function.get('name') or ''), arguments)
            )
        usage = payload.get('usage') or {}
        tokens = int(usage.get('total_tokens') or 0)
        if not tokens:  # some local servers omit usage: estimate (4 characters per token)
            tokens = (sent_chars + len(response.text) + 3) // 4
        return ChatResult(
            content=str(message.get('content') or ''),
            tool_calls=tuple(calls),
            tokens=tokens,
            raw_tool_calls=raw_calls,
        )
