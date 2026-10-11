"""Telemetry types — single source of truth for enums and payloads."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, TypedDict


class ErrorSeverity(StrEnum):
    DEBUG = 'DEBUG'
    INFO = 'INFO'
    WARNING = 'WARNING'
    ERROR = 'ERROR'
    CRITICAL = 'CRITICAL'


class ErrorStatus(StrEnum):
    OPEN = 'OPEN'
    ACKED = 'ACKED'
    RESOLVED = 'RESOLVED'
    MUTED = 'MUTED'


class ErrorSource(StrEnum):
    DJANGO = 'DJANGO'
    CELERY = 'CELERY'
    CSP = 'CSP'
    HTTP = 'HTTP'
    HEALTH = 'HEALTH'
    MANUAL = 'MANUAL'
    LOGGING = 'LOGGING'


class ErrorContext(TypedDict, total=False):
    correlation_id: str
    request_path: str
    method: str
    view_name: str
    user: str
    release: str
    environment: str
    extra: dict[str, Any]


__all__ = ['ErrorContext', 'ErrorSeverity', 'ErrorSource', 'ErrorStatus']
