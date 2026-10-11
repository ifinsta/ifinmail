import enum


class EndpointIntent(enum.Enum):
    """Semantic classification of what an endpoint does."""

    LIST = "list"  # Collection endpoint (GET returns multiple items)
    DETAIL = "detail"  # Single-resource endpoint (requires pk/id)
    ACTION = "action"  # RPC-style action (login, verify, mark_read)
    SINGLETON = "singleton"  # Resource without pk (me, current, status)
    ROOT = "root"  # API root / discovery endpoint
