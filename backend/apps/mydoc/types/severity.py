from enum import Enum


class Severity(str, Enum):
    """Audit finding severity level."""

    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"
