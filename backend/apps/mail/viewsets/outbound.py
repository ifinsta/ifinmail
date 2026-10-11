"""Outbound (Postfix runtime) viewset — read/tune delivery settings."""

from __future__ import annotations

from backend.apps.mail.serializers import OutboundStateOut
from backend.apps.mail.services.postfix_runtime import PostfixRuntime


def get_outbound_state() -> OutboundStateOut:
    return OutboundStateOut.from_state(PostfixRuntime.state())


def set_smart_host(enabled: bool) -> OutboundStateOut:
    return OutboundStateOut.from_state(PostfixRuntime.set_smart_host(enabled))


def set_smtp_proxy(enabled: bool) -> OutboundStateOut:
    return OutboundStateOut.from_state(PostfixRuntime.set_smtp_proxy(enabled))


def set_max_hops(value: int) -> OutboundStateOut:
    return OutboundStateOut.from_state(PostfixRuntime.set_max_hops(value))


def render_outbound() -> str:
    """The exact ``key = value`` text the postfix container applies."""
    return PostfixRuntime.render()


__all__ = [
    'get_outbound_state',
    'render_outbound',
    'set_max_hops',
    'set_smart_host',
    'set_smtp_proxy',
]
