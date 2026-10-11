"""Mailbox quota defaults and the space budget.

``0`` keeps its meaning of *unlimited*; it is simply no longer the default.
Every mailbox created without an explicit quota gets ``DEFAULT_QUOTA_BYTES``.
"""

from __future__ import annotations

from dataclasses import dataclass

MB = 1024 * 1024
DEFAULT_QUOTA_MB = 1024
DEFAULT_QUOTA_BYTES = DEFAULT_QUOTA_MB * MB


@dataclass(frozen=True)
class QuotaBudget:
    """How much mailbox quota the mail volume can still promise.

    ``disk_total_bytes``/``disk_free_bytes`` are ``None`` when the disk could
    not be inspected; ``headroom_bytes`` is then ``None`` as well.
    """

    disk_total_bytes: int | None
    disk_free_bytes: int | None
    allocated_bytes: int
    mailbox_count: int
    unlimited_count: int

    @property
    def headroom_bytes(self) -> int | None:
        """Disk size minus all finite quotas; negative means overcommitted."""
        if self.disk_total_bytes is None:
            return None
        return self.disk_total_bytes - self.allocated_bytes

    @property
    def overcommitted(self) -> bool:
        headroom = self.headroom_bytes
        return headroom is not None and headroom < 0


def human_bytes(size: int | None) -> str:
    """Compact size label ('3.4 GB', '-2.0 GB'); an em dash when unknown."""
    if size is None:
        return '—'
    sign = '-' if size < 0 else ''
    size = abs(size)
    if size >= 1024**4:
        return f'{sign}{size / 1024**4:.1f} TB'
    if size >= 1024**3:
        return f'{sign}{size / 1024**3:.1f} GB'
    if size >= 1024**2:
        return f'{sign}{size / 1024**2:.0f} MB'
    if size >= 1024:
        return f'{sign}{size / 1024:.0f} KB'
    return f'{sign}{size} B'


__all__ = ['DEFAULT_QUOTA_BYTES', 'DEFAULT_QUOTA_MB', 'MB', 'QuotaBudget', 'human_bytes']
