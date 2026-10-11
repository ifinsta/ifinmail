"""DNS jobs: keep the authoritative zones published."""

from __future__ import annotations

import logging

from celery import shared_task

from .services.server import DNSServerConfig
from .services.zones import ZoneService

logger = logging.getLogger('backend')


@shared_task(name='dns.publish_zones')
def publish_zones() -> list[str]:
    """Re-render every authoritative zone (picks up a new DKIM key, address or setting)."""
    if not DNSServerConfig.enabled():
        return []
    return ZoneService.publish().zones
