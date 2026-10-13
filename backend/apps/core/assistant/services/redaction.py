"""Keep secrets out of what is sent to the model.

Tool results pass through ``redact`` before they leave the server: values under secret-looking
keys are replaced, secret-looking strings are masked, and the whole result is capped in size.
Message content (bodies, subjects, attachments) is never available to tools in the first place.
"""

from __future__ import annotations

import json
import re

from backend.apps.core.assistant.types import MAX_TOOL_OUTPUT_CHARS

REDACTED = '[redacted]'
_SECRET_KEY_RE = re.compile(
    r'(pass(word|phrase)?|secret|token|api[_-]?key|private|credential|otp|totp)', re.I
)
_SECRET_VALUE_RES = (
    re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----', re.S),
    re.compile(r'\b(?:plugin-secret|fernet):[A-Za-z0-9_\-=]+'),
    re.compile(r'\bsk-[A-Za-z0-9_\-]{16,}'),  # OpenAI-style keys
    re.compile(r'\b(?:xox[abp]|ghp|gho|glpat)-?[A-Za-z0-9_\-]{16,}'),
    re.compile(r'(?i)\bbearer\s+[A-Za-z0-9._\-]{16,}'),
    re.compile(r'\bifs_[A-Za-z0-9_\-]{16,}'),  # an ifinmail API secret
    re.compile(r'\bifm\.[A-Za-z0-9]{6,}\.[A-Za-z0-9_\-]{16,}'),  # an ifinmail Bearer token
    re.compile(r'(?i)(password|passwd|pwd)\s*[=:]\s*\S+'),
)


def _scrub(text: str) -> str:
    for pattern in _SECRET_VALUE_RES:
        text = pattern.sub(REDACTED, text)
    return text


def _walk(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(k): REDACTED if _SECRET_KEY_RE.search(str(k)) else _walk(v)
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [_walk(v) for v in value]
    if isinstance(value, str):
        return _scrub(value)
    if value is None or isinstance(value, bool | int | float):
        return value
    return _scrub(str(value))


def redact(value: object) -> str:
    """JSON text of ``value`` with secrets removed, at most MAX_TOOL_OUTPUT_CHARS long."""
    text = json.dumps(_walk(value), ensure_ascii=False, default=str)
    if len(text) > MAX_TOOL_OUTPUT_CHARS:
        text = text[: MAX_TOOL_OUTPUT_CHARS - 40] + '... [truncated: ask a narrower question]'
    return text
