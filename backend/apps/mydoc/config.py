"""
MyDoc Pluggable Configuration

All settings are read from Django settings.MYDOC_CONFIG.
This makes the app fully portable -- drop into any Django+DRF
project and configure via a single dictionary.
"""

from typing import Any

from django.conf import settings

DEFAULTS = {
    # Branding
    "TITLE": "API Documentation",
    "DESCRIPTION": "Auto-generated from live endpoints.",
    "LOGO_TEXT": "MyDoc",
    "ACCENT_COLOR": "#10b981",
    # Security
    "REQUIRE_AUTH": False,
    "ALLOWED_GROUPS": [],  # empty = all authenticated users
    # Introspection
    "EXCLUDE_PATTERNS": [
        "back-office/",
        "__debug__/",
        "static/",
        "media/",
        "mydoc/",
    ],
    "EXCLUDE_NAMESPACES": [],
    "ALLOWED_METHODS": ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    # Playground
    "PLAYGROUND_ENABLED": True,
    "PLAYGROUND_DEFAULT_CONTENT_TYPE": "application/json",
    "PLAYGROUND_MAX_HISTORY": 25,
    # OpenAPI
    "OPENAPI_ENABLED": True,
    "OPENAPI_VERSION": "3.0.3",
    # Caching
    "CACHE_TTL": 300,  # seconds, 0 to disable
    "CACHE_ENABLED": True,
    # Audit
    "REPORT_OUTPUT_PATH": None,  # None = auto (project root / MYDOC_AUDIT_REPORT.md)
    # Logging
    "LOG_LEVEL": "INFO",  # DEBUG, INFO, WARNING, ERROR
    # Code snippets
    "CODE_SNIPPETS": ["curl", "python", "javascript"],
    # Base URL override (None = auto-detect from request)
    "BASE_URL": None,
    # Environment switcher
    "ENVIRONMENTS": [],
    # Example: [
    #     {"name": "Local", "url": "http://localhost:8009"},
    #     {"name": "Staging", "url": "https://staging.example.com"},
    #     {"name": "Production", "url": "https://api.example.com"},
    # ]
}


def get_config() -> dict:
    """Get merged configuration (user settings override defaults)."""
    user_config = getattr(settings, "MYDOC_CONFIG", {})
    merged = {**DEFAULTS, **user_config}
    return merged


def get_setting(key: str, default: Any = None) -> Any:
    """Get a single configuration value."""
    config = get_config()
    return config.get(key, default)
