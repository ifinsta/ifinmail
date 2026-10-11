"""telemetry — hooks.py: extension points for alerts/digests."""

from __future__ import annotations

from typing import Any


def on_critical_error(event: dict[str, Any]) -> None:
    """Hook fired after a CRITICAL error is persisted (override per deploy)."""
