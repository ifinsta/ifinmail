"""Is a newer ifinmail release published? Compares APP_VERSION with the repository's tags.

provision.sh records APP_VERSION from ``git describe --tags`` (``v0.0.3`` on a release,
``v0.0.3-2-gabc123`` a few commits after it). A beat task asks GitHub for the tags every six
hours; the answer is kept in system settings so the dashboard and System health never wait on
the network. Admins can switch the check off (no request then leaves the server).
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime

logger = logging.getLogger('backend')

_TAG_RE = re.compile(r'^v?(\d+)\.(\d+)\.(\d+)$')
_DESCRIBE_RE = re.compile(r'^v?(\d+)\.(\d+)\.(\d+)(?:-(\d+)-g[0-9a-f]+)?(?:-dirty)?$')


def parse_version(text: str) -> tuple[int, int, int, int] | None:
    """(major, minor, patch, commits after the tag) for a tag or git-describe string."""
    match = _DESCRIBE_RE.match((text or '').strip())
    if not match:
        return None
    major, minor, patch, ahead = match.groups()
    return int(major), int(minor), int(patch), int(ahead or 0)


@dataclass(frozen=True)
class UpdateStatus:
    enabled: bool
    current: str
    latest: str = ''
    checked_at: str = ''
    error: str = ''
    repo: str = ''

    @property
    def available(self) -> bool:
        mine, theirs = parse_version(self.current), parse_version(self.latest)
        if not mine or not theirs:
            return False
        return theirs[:3] > mine[:3]

    @property
    def release_url(self) -> str:
        return f'https://github.com/{self.repo}/releases/tag/{self.latest}' if self.latest else ''

    @property
    def changes_url(self) -> str:
        if not self.latest or not parse_version(self.current):
            return self.release_url
        base = self.current.split('-')[0]
        return f'https://github.com/{self.repo}/compare/{base}...{self.latest}'


class UpdateService:
    @staticmethod
    def repo() -> str:
        return os.environ.get('UPDATE_REPO', 'ifinsta/ifinmail').strip() or 'ifinsta/ifinmail'

    @staticmethod
    def current() -> str:
        return os.environ.get('APP_VERSION', 'dev').strip() or 'dev'

    @staticmethod
    def enabled() -> bool:
        if os.environ.get('UPDATE_CHECK_ENABLED', '1').strip() == '0':
            return False
        from backend.apps.core.services import SystemSettings
        from backend.apps.core.types import SettingKey

        return SystemSettings.get_bool(SettingKey.UPDATE_CHECK_ENABLED, True)

    @staticmethod
    def set_enabled(value: bool) -> None:
        from backend.apps.core.services import SystemSettings
        from backend.apps.core.types import SettingKey

        SystemSettings.set(SettingKey.UPDATE_CHECK_ENABLED, bool(value))

    @staticmethod
    def status() -> UpdateStatus:
        from backend.apps.core.services import SystemSettings
        from backend.apps.core.types import SettingKey

        stored = SystemSettings.get(SettingKey.UPDATE_LATEST) or {}
        if not isinstance(stored, dict):
            stored = {}
        return UpdateStatus(
            enabled=UpdateService.enabled(),
            current=UpdateService.current(),
            latest=str(stored.get('latest', '')),
            checked_at=str(stored.get('checked_at', '')),
            error=str(stored.get('error', '')),
            repo=UpdateService.repo(),
        )

    @staticmethod
    def latest_release_tag() -> str:
        """Highest vX.Y.Z tag of the repository on GitHub (raises on network/API errors)."""
        import requests

        response = requests.get(
            f'https://api.github.com/repos/{UpdateService.repo()}/tags',
            params={'per_page': 100},
            headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'ifinmail-update-check'},
            timeout=8,
        )
        response.raise_for_status()
        versions = [
            (parse_version(item.get('name', '')), item.get('name', ''))
            for item in response.json()
            if _TAG_RE.match(item.get('name', ''))
        ]
        versions = [v for v in versions if v[0]]
        return max(versions)[1] if versions else ''

    @staticmethod
    def check() -> UpdateStatus:
        """Ask GitHub now (when enabled) and remember the answer."""
        from backend.apps.core.services import SystemSettings
        from backend.apps.core.types import SettingKey

        if not UpdateService.enabled():
            return UpdateService.status()
        previous = UpdateService.status()
        record = {'latest': previous.latest, 'checked_at': datetime.now(UTC).isoformat(), 'error': ''}
        try:
            record['latest'] = UpdateService.latest_release_tag() or previous.latest
        except Exception as exc:  # network, rate limit, API change: keep the last good answer
            logger.warning('Update check failed: %s', exc)
            record['error'] = 'Could not reach GitHub to check for updates.'
        SystemSettings.set(SettingKey.UPDATE_LATEST, record)
        return UpdateService.status()
