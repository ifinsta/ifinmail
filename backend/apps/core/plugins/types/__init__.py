"""Plugin types: states, operations, the transition table and errors.

The tables here are the single source of truth for both state machines; services consult them and
never encode transitions inline. See .agents/skills/ifinmail-plugins/references/state-machines.md.
"""

from __future__ import annotations

from enum import StrEnum

MANIFEST_VERSION = 1
MAX_MANIFEST_BYTES = 32 * 1024
STALE_SECONDS = 120


class InstallationState(StrEnum):
    INSTALLING = 'installing'
    ENABLED = 'enabled'
    DISABLED = 'disabled'
    APPLYING = 'applying'
    UNINSTALLING = 'uninstalling'
    FAILED = 'failed'


TRANSIENT_STATES = frozenset(
    {InstallationState.INSTALLING, InstallationState.APPLYING, InstallationState.UNINSTALLING}
)


class Operation(StrEnum):
    INSTALL = 'install'
    ENABLE = 'enable'
    DISABLE = 'disable'
    CONFIGURE = 'configure'
    UPDATE = 'update'
    RETRY = 'retry'
    UNINSTALL = 'uninstall'


# Sentinel for "no row" (not installed) and "row removed" (uninstall target).
ABSENT = 'absent'

# operation -> (states it may start from, transient state while it runs, target or None = keep)
TRANSITIONS: dict[Operation, tuple[frozenset[str], InstallationState, str | None]] = {
    Operation.INSTALL: (
        frozenset({ABSENT}),
        InstallationState.INSTALLING,
        InstallationState.ENABLED,
    ),
    Operation.ENABLE: (
        frozenset({InstallationState.DISABLED}),
        InstallationState.APPLYING,
        InstallationState.ENABLED,
    ),
    Operation.DISABLE: (
        frozenset({InstallationState.ENABLED}),
        InstallationState.APPLYING,
        InstallationState.DISABLED,
    ),
    Operation.CONFIGURE: (
        frozenset({InstallationState.ENABLED, InstallationState.DISABLED}),
        InstallationState.APPLYING,
        None,
    ),
    Operation.UPDATE: (
        frozenset({InstallationState.ENABLED, InstallationState.DISABLED}),
        InstallationState.APPLYING,
        None,
    ),
    # Retry heads for the target recorded when the row failed (resolved at run time).
    Operation.RETRY: (frozenset({InstallationState.FAILED}), InstallationState.APPLYING, None),
    Operation.UNINSTALL: (
        frozenset(
            {InstallationState.ENABLED, InstallationState.DISABLED, InstallationState.FAILED}
        ),
        InstallationState.UNINSTALLING,
        ABSENT,
    ),
}


def allowed_operations(state: str) -> list[Operation]:
    """Operations the table allows from ``state`` (``ABSENT`` for not installed)."""
    return [op for op, (sources, _, _) in TRANSITIONS.items() if state in sources]


class SubmissionState(StrEnum):
    SUBMITTED = 'submitted'
    APPROVED = 'approved'
    REJECTED = 'rejected'
    WITHDRAWN = 'withdrawn'
    RETIRED = 'retired'


# A plugin id + version is "live" (cannot be submitted again) in these states.
LIVE_SUBMISSION_STATES = frozenset(
    {SubmissionState.SUBMITTED, SubmissionState.APPROVED, SubmissionState.RETIRED}
)

SUBMISSION_TRANSITIONS: dict[str, tuple[frozenset[str], SubmissionState]] = {
    'approve': (frozenset({SubmissionState.SUBMITTED}), SubmissionState.APPROVED),
    'reject': (frozenset({SubmissionState.SUBMITTED}), SubmissionState.REJECTED),
    'withdraw': (frozenset({SubmissionState.SUBMITTED}), SubmissionState.WITHDRAWN),
    'retire': (frozenset({SubmissionState.APPROVED}), SubmissionState.RETIRED),
}


class PluginSource(StrEnum):
    BUNDLED = 'bundled'
    SUBMITTED = 'submitted'


class ApplyStatus(StrEnum):
    APPLIED = 'applied'
    APPLYING = 'applying'
    NOT_APPLIED = 'not_applied'
    UNKNOWN = 'unknown'


CATEGORIES = ('compliance', 'security', 'delivery', 'operations', 'integration')


class PluginError(Exception):
    """Base error; the message is safe to show to an administrator."""


class ManifestError(PluginError):
    """The manifest is invalid. ``problems`` lists every problem as ``(location, message)``."""

    def __init__(self, problems: list[tuple[str, str]]) -> None:
        self.problems = problems
        first = problems[0] if problems else ('manifest', 'invalid')
        more = f' (and {len(problems) - 1} more)' if len(problems) > 1 else ''
        super().__init__(f'{first[0]}: {first[1]}{more}')


class SettingsError(PluginError):
    """Submitted settings are invalid. ``errors`` maps setting key to message."""

    def __init__(self, errors: dict[str, str]) -> None:
        self.errors = errors
        super().__init__('; '.join(f'{k}: {v}' for k, v in errors.items()))


class TransitionError(PluginError):
    """The operation is not allowed from the current state."""


class BusyError(PluginError):
    """Another operation is in progress on this plugin."""


class StaleRevisionError(PluginError):
    """The installation changed since the page was loaded."""


class ConflictError(PluginError):
    """Another enabled plugin already sets one of the same values."""


class NotFoundError(PluginError):
    """No such plugin, installation or submission."""
