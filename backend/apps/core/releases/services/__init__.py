"""releases — service layer (single interface for app releases and device update checks)."""

from backend.apps.core.releases.services.apk import ApkError, ApkInfo, inspect_apk
from backend.apps.core.releases.services.release_service import (
    AdoptionRow,
    ReleaseService,
    UpdateDecision,
    manifest_for,
    rollout_bucket,
)

__all__ = [
    'AdoptionRow',
    'ApkError',
    'ApkInfo',
    'ReleaseService',
    'UpdateDecision',
    'inspect_apk',
    'manifest_for',
    'rollout_bucket',
]
