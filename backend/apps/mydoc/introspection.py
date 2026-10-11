"""
MyDoc API Introspection Engine

Automatically discovers all DRF endpoints, serializers, viewsets and builds
a structured documentation tree.  Supports dynamic parameter resolution:
URL params are extracted from both Django path converters (<type:name>) and
regex named groups ((?P<name>...)), producing clean display paths and
semantic endpoint classification.
"""

from __future__ import annotations

import inspect
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from django.core.cache import cache
from django.urls import URLPattern, URLResolver, get_resolver

from ._native import (
    is_native_available as _is_native_available,
)
from ._native import (
    normalize_path_native as _normalize_path_native,
)
from ._native import (
    resolve_url_params_native as _resolve_url_params_native,
)
from .config import get_setting
from .types import EndpointIntent

logger = logging.getLogger(__name__)

# Log native acceleration status at import time
if _is_native_available():
    logger.info("MyDoc: Cython native acceleration loaded")
else:
    logger.debug("MyDoc: Using pure-Python implementations (Cython not compiled)")

# =========================================================================
# PROCESS-LEVEL CACHES (Phase 1 — never changes at runtime)
# =========================================================================

# Serializer field metadata cache: qualname → (name, [FieldInfo])
_serializer_cache: dict[str, tuple[str, list[FieldInfo]]] = {}
# Permission class-name cache: qualname → list[str]
_permission_cache: dict[str, list[str]] = {}
# Frozen search index: list of pre-built search records
_search_index: list[dict] | None = None
_search_index_timestamp: float = 0.0

# Regex for DRF format-suffix patterns (DefaultRouter duplicates)
_FORMAT_SUFFIX_RE = re.compile(r"\(\?P<format>\[")

# HTTP method colors/badges mapping
METHOD_STYLES = {
    "GET": {"color": "#10b981", "bg": "rgba(16, 185, 129, 0.12)", "label": "GET"},
    "POST": {"color": "#3b82f6", "bg": "rgba(59, 130, 246, 0.12)", "label": "POST"},
    "PUT": {"color": "#f59e0b", "bg": "rgba(245, 158, 11, 0.12)", "label": "PUT"},
    "PATCH": {"color": "#8b5cf6", "bg": "rgba(139, 92, 246, 0.12)", "label": "PATCH"},
    "DELETE": {"color": "#ef4444", "bg": "rgba(239, 68, 68, 0.12)", "label": "DELETE"},
    "HEAD": {"color": "#6b7280", "bg": "rgba(107, 114, 128, 0.12)", "label": "HEAD"},
    "OPTIONS": {"color": "#6b7280", "bg": "rgba(107, 114, 128, 0.12)", "label": "OPTIONS"},
}


# =========================================================================
# URL PARAMETER RESOLUTION
# =========================================================================

# Matches Django path converters: <int:pk>, <str:slug>, <uuid:id>, <pk>
_PATH_CONVERTER_RE = re.compile(r"<(?:(?P<type>\w+):)?(?P<name>\w+)>")
# Matches regex named groups: (?P<pk>[^/.]+), (?P<slug>[\w-]+)
_REGEX_NAMED_GROUP_RE = re.compile(r"\(\?P<(?P<name>\w+)>[^)]+\)")
# Regex anchors and optional trailing-slash noise
_REGEX_NOISE_RE = re.compile(r"[\^$]")
# Common regex type patterns → semantic type mapping
_REGEX_TYPE_MAP = {
    r"[0-9]+": "int",
    r"\d+": "int",
    r"[^/.]+": "str",
    r"[\w-]+": "slug",
    r"[0-9a-f-]{36}": "uuid",
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}": "uuid",
}


@dataclass
class UrlParam:
    """A resolved URL parameter extracted from the endpoint path."""

    name: str
    param_type: str = "str"  # int, str, slug, uuid, path
    required: bool = True
    pattern: str = ""  # raw regex pattern, if any

    @property
    def display(self) -> str:
        """Human-readable display: {pk:int} or {slug}."""
        if self.param_type and self.param_type != "str":
            return f"{{{self.name}:{self.param_type}}}"
        return f"{{{self.name}}}"


# Words that indicate an action (RPC) rather than a resource
_ACTION_SEGMENTS = frozenset({
    "login", "logout", "register", "signup", "verify", "confirm",
    "reset", "setup", "send", "check", "activate", "deactivate",
    "suspend", "terminate", "approve", "reject", "cancel",
    "mark-read", "mark_read", "mark-all-read", "mark_all_read",
    "invite", "resend", "revoke", "export", "import", "sync",
    "test", "validate", "refresh", "heartbeat", "ping",
    "initiate", "complete", "submit", "upload", "download",
    "transfer", "pay", "charge", "refund", "void",
    "lock", "unlock", "archive", "unarchive", "restore",
    "unread-count",
})

# Words that indicate a singleton resource (no pk needed)
_SINGLETON_SEGMENTS = frozenset({
    "me", "current", "profile", "status", "summary",
    "dashboard", "config", "settings", "preferences",
    "eligibility", "plans", "overview",
})


def _resolve_url_params(raw_path: str) -> list[UrlParam]:
    """Extract URL parameters from both converter and regex styles.

    Phase 2.6: Delegates to Cython-accelerated native for extraction,
    then converts dicts back to UrlParam dataclass instances.
    """
    raw_params = _resolve_url_params_native(raw_path)
    return [
        UrlParam(
            name=p["name"],
            param_type=p["param_type"],
            required=p["required"],
            pattern=p["pattern"],
        )
        for p in raw_params
    ]


def _normalize_path(raw_path: str) -> str:
    """Convert a raw URL pattern to a clean, human-readable path.

    Phase 2.6: Delegates to Cython-accelerated native when available.
    """
    return _normalize_path_native(raw_path)


def _infer_endpoint_intent(
    path: str,
    methods: list[str],
    view_class_name: str,
    action_name: str,
    url_params: list[UrlParam],
) -> EndpointIntent:
    """Classify endpoint semantics from its resolved metadata."""
    if view_class_name == "APIRootView":
        return EndpointIntent.ROOT

    clean = _normalize_path(path)
    segments = [s for s in clean.strip("/").split("/") if s and not s.startswith("{")]
    last_raw_segment = clean.rstrip("/").split("/")[-1] if clean.rstrip("/") else ""

    # If the last path segment is a URL parameter → detail
    if last_raw_segment.startswith("{"):
        return EndpointIntent.DETAIL

    # If the last segment is a known action word → action
    last_segment = segments[-1].lower() if segments else ""
    if last_segment in _ACTION_SEGMENTS:
        return EndpointIntent.ACTION

    # If the last segment is a known singleton → singleton
    if last_segment in _SINGLETON_SEGMENTS:
        return EndpointIntent.SINGLETON

    # If the action_name looks like an action
    if action_name and action_name.replace("_", "-") in _ACTION_SEGMENTS:
        return EndpointIntent.ACTION

    # Write-only endpoints without GET are usually actions
    if "GET" not in methods and any(m in methods for m in ("POST", "PUT", "PATCH", "DELETE")):
        return EndpointIntent.ACTION

    # Fallback: if it has GET and no pk params → list
    if "GET" in methods:
        return EndpointIntent.LIST

    return EndpointIntent.ACTION


@dataclass
class FieldInfo:
    """Represents a serializer field."""

    name: str
    field_type: str
    required: bool = False
    read_only: bool = False
    write_only: bool = False
    help_text: str = ""
    max_length: int | None = None
    choices: list | None = None
    default: Any = None
    source: str = ""


@dataclass
class SerializerInfo:
    """Serializer metadata resolved for one HTTP method and transport role."""

    name: str = ""
    fields: list[FieldInfo] = field(default_factory=list)


@dataclass
class EndpointInfo:
    """Represents a single API endpoint."""

    path: str
    methods: list[str] = field(default_factory=list)
    view_name: str = ""
    view_class: str = ""
    docstring: str = ""
    description: str = ""
    request_serializer_name: str = ""
    request_serializer_fields: list[FieldInfo] = field(default_factory=list)
    response_serializer_name: str = ""
    response_serializer_fields: list[FieldInfo] = field(default_factory=list)
    request_serializers: dict[str, SerializerInfo] = field(default_factory=dict)
    response_serializers: dict[str, SerializerInfo] = field(default_factory=dict)
    # Backwards-compatible response aliases used by existing MyDoc consumers.
    serializer_name: str = ""
    serializer_fields: list[FieldInfo] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    write_permissions: list[str] = field(default_factory=list)
    authentication: list[str] = field(default_factory=list)
    filter_backends: list[str] = field(default_factory=list)
    throttle_classes: list[str] = field(default_factory=list)
    public_write_controls: list[str] = field(default_factory=list)
    pagination_class: str = ""
    url_name: str = ""
    namespace: str = ""
    is_detail: bool = False
    action_name: str = ""
    tags: list[str] = field(default_factory=list)
    # Dynamic parameter resolution fields
    url_params: list[UrlParam] = field(default_factory=list)
    display_path: str = ""
    intent: EndpointIntent = EndpointIntent.LIST

    @property
    def slug(self) -> str:
        """Generate a URL-safe slug for this endpoint."""
        clean = self.path.strip("/").replace("/", "-").replace("<", "").replace(">", "")
        clean = re.sub(r"[^a-zA-Z0-9\-]", "", clean)
        return clean or "root"

    @property
    def method_styles(self) -> list[dict]:
        """Get style info for each method."""
        return [
            {**METHOD_STYLES.get(m.upper(), METHOD_STYLES["GET"]), "method": m.upper()}
            for m in self.methods
        ]

    @property
    def short_description(self) -> str:
        """Get first line of docstring as short description."""
        if self.description:
            return self.description.split("\n")[0].strip()
        if self.docstring:
            lines = [l.strip() for l in self.docstring.strip().split("\n") if l.strip()]
            return lines[0] if lines else ""
        return ""

    def request_serializer_for(self, method: str) -> SerializerInfo:
        """Return request serializer metadata for an HTTP method."""
        return self.request_serializers.get(
            method.upper(),
            SerializerInfo(
                name=self.request_serializer_name,
                fields=self.request_serializer_fields,
            ),
        )

    def response_serializer_for(self, method: str) -> SerializerInfo:
        """Return response serializer metadata for an HTTP method."""
        return self.response_serializers.get(
            method.upper(),
            SerializerInfo(
                name=self.response_serializer_name or self.serializer_name,
                fields=self.response_serializer_fields or self.serializer_fields,
            ),
        )


@dataclass
class SectionInfo:
    """Represents a group of related endpoints (e.g., an app)."""

    name: str
    slug: str
    description: str = ""
    icon: str = ""
    endpoints: list[EndpointInfo] = field(default_factory=list)
    subsections: dict[str, list[EndpointInfo]] = field(default_factory=dict)

    @property
    def endpoint_count(self) -> int:
        total = len(self.endpoints)
        for eps in self.subsections.values():
            total += len(eps)
        return total

    @property
    def method_summary(self) -> dict[str, int]:
        """Count of each HTTP method in this section."""
        counts: dict[str, int] = {}
        all_eps = list(self.endpoints)
        for eps in self.subsections.values():
            all_eps.extend(eps)
        for ep in all_eps:
            for m in ep.methods:
                counts[m.upper()] = counts.get(m.upper(), 0) + 1
        return counts


# Section icon mapping based on app name — uses SVG icon identifiers (no emojis)
SECTION_ICONS = {
    "accounts": "user",
    "wallet": "wallet",
    "payments": "credit-card",
    "merchants": "store",
    "geo": "globe",
    "preferences": "sliders",
    "settings": "settings",
    "subscriptions": "package",
    "verifications": "check-circle",
    "terminals": "smartphone",
    "partners": "handshake",
    "integrations": "link",
    "notifications": "bell",
    "survey": "clipboard",
    "seo": "search",
    "storage": "folder",
    "inventory": "box",
    "customers": "users",
    "reports": "bar-chart",
    "hr": "hard-hat",
    "procurement": "shopping-cart",
    "expenses": "dollar-sign",
    "loyalty": "star",
    "sales": "shopping-bag",
    "marketplace": "grid",
    "discover": "shopping-bag",
    "debt": "file-text",
    "messaging": "message-circle",
    "appointments": "calendar",
    "health": "heart",
    "security": "shield",
    "contacts": "book",
    "performance": "zap",
    "trash": "trash-2",
}


def _get_view_class(callback: Any) -> type | None:
    """Extract the actual view class from a callback."""
    if hasattr(callback, "cls"):
        return callback.cls
    if hasattr(callback, "view_class"):
        return callback.view_class
    if hasattr(callback, "initkwargs") and "cls" in callback.initkwargs:
        return callback.initkwargs["cls"]
    return None


def _get_view_methods(callback, view_class) -> list[str]:
    """Get HTTP methods supported by a view."""
    methods = []

    # Check for actions mapping (ViewSet)
    if hasattr(callback, "actions"):
        actions = callback.actions
        if isinstance(actions, dict):
            methods = [m.upper() for m in actions.keys()]
            return sorted(set(methods))

    # Check initkwargs for actions
    if hasattr(callback, "initkwargs"):
        actions = callback.initkwargs.get("actions", {})
        if actions:
            methods = [m.upper() for m in actions.keys()]
            return sorted(set(methods))

    # Fall back to view class http_method_names
    if view_class:
        http_methods = getattr(view_class, "http_method_names", [])
        # Filter to only methods that have handlers
        for method in http_methods:
            if method.upper() in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
                if hasattr(view_class, method.lower()):
                    methods.append(method.upper())

    return sorted(set(methods)) if methods else ["GET"]


def _inspect_view_serializer(view_class) -> tuple[str, list[FieldInfo]]:
    """Extract serializer class name and field information.

    Supports dynamic resolution: tries ``serializer_class`` first, then
    falls back to ``get_serializer_class()`` for ViewSets that determine
    the serializer at runtime.

    Results are cached at process level (serializer field metadata
    never changes at runtime).
    """
    serializer_class = getattr(view_class, "serializer_class", None)

    # Dynamic fallback: views with get_serializer_class() resolve at runtime.
    # The class-level call (view_class.get_serializer_class(view_class))
    # fails because realistic implementations reference self.action.
    # Trust that any ViewSet with dynamic resolution handles serialization
    # correctly — return a marker so the auditor skips MISSING_SERIALIZER.
    if not serializer_class and hasattr(view_class, "get_serializer_class"):
        return ("<dynamic>", [])

    # Plain ViewSet subclasses (without get_serializer_class, without
    # static serializer_class) handle serialization manually in each
    # action method — this is by design, not a gap.
    if not serializer_class:
        try:
            from rest_framework.viewsets import ViewSet

            if issubclass(view_class, ViewSet):
                return ("<viewset>", [])
        except (ImportError, TypeError):
            pass

    if not serializer_class:
        return "", []

    # ── Phase 1.1: Process-level cache (serializer fields never change) ──
    cache_key = f"{serializer_class.__module__}.{serializer_class.__qualname__}"
    if cache_key in _serializer_cache:
        return _serializer_cache[cache_key]

    name = serializer_class.__name__
    fields: list[FieldInfo] = []

    # Determine whether this is a ModelSerializer (for model-field fallback)
    _is_model_serializer = (
        hasattr(serializer_class, "Meta")
        and hasattr(serializer_class.Meta, "model")
    )
    _model = serializer_class.Meta.model if _is_model_serializer else None

    try:
        serializer = serializer_class()
        for field_name, field_obj in serializer.fields.items():
            field_type = type(field_obj).__name__
            max_length = getattr(field_obj, "max_length", None)
            source = getattr(field_obj, "source", "") or ""

            # ── ModelSerializer fallback for max_length ──
            # DRF maps model TextField to CharField with max_length=None
            # which the auditor flags as MISSING_MAX_LENGTH.  If the
            # underlying model field is a CharField, inherit its max_length.
            # If it is a TextField, None is intentional (unlimited).
            if _is_model_serializer and max_length is None and field_type in ("CharField", "TextField"):
                try:
                    model_field_name = source or field_name
                    model_field = _model._meta.get_field(model_field_name)
                    model_max = getattr(model_field, "max_length", None)
                    if model_max is not None:
                        max_length = model_max
                except Exception:
                    pass  # Can't resolve model field; leave as-is

            fi = FieldInfo(
                name=field_name,
                field_type=field_type,
                required=getattr(field_obj, "required", False),
                read_only=getattr(field_obj, "read_only", False),
                write_only=getattr(field_obj, "write_only", False),
                help_text=str(getattr(field_obj, "help_text", "") or ""),
                max_length=max_length,
                source=source,
            )

            choices = getattr(field_obj, "choices", None)
            if choices:
                fi.choices = list(choices.keys()) if isinstance(choices, dict) else list(choices)

            default = getattr(field_obj, "default", None)
            if default is not None and not callable(default):
                fi.default = str(default)

            fields.append(fi)
    except Exception as e:
        logger.debug(f"Could not inspect serializer {name}: {e}")

    result = (name, fields)
    _serializer_cache[cache_key] = result
    return result


def _inspect_serializer_class(serializer_class) -> tuple[str, list[FieldInfo]]:
    """Inspect a serializer class using the shared field metadata cache."""
    if serializer_class is None:
        return "", []
    holder = type(
        "_SerializerHolder",
        (),
        {"serializer_class": serializer_class},
    )
    return _inspect_view_serializer(holder)


def _get_serializer_info(view_class) -> tuple[str, list[FieldInfo]]:
    """Return class-level serializer metadata for backwards compatibility."""
    return _inspect_view_serializer(view_class)


def _action_method(view_class, action_name: str):
    """Return a ViewSet action method when one is declared."""
    if not action_name or not hasattr(view_class, action_name):
        return None
    return getattr(view_class, action_name)


def _resolve_route_serializer_class(callback, view_class, action_name: str):
    """Resolve the serializer DRF would select for a concrete route action."""
    action_method = _action_method(view_class, action_name)
    action_kwargs = getattr(action_method, "kwargs", {}) if action_method else {}
    initkwargs = getattr(callback, "initkwargs", {}) or {}

    serializer_class = (
        initkwargs.get("serializer_class")
        or action_kwargs.get("serializer_class")
    )
    if serializer_class:
        return serializer_class

    try:
        view = view_class()
        for name, value in initkwargs.items():
            setattr(view, name, value)
        view.action = action_name
        view.request = None
        view.args = ()
        view.kwargs = {}
        return view.get_serializer_class()
    except Exception:
        return getattr(view_class, "serializer_class", None)


def _get_endpoint_serializer_info(
    callback,
    view_class,
) -> tuple[dict[str, SerializerInfo], dict[str, SerializerInfo]]:
    """Resolve request and response serializers for every routed HTTP method."""
    actions = getattr(callback, "actions", None) or {}
    if not actions:
        initkwargs = getattr(callback, "initkwargs", {}) or {}
        actions = initkwargs.get("actions", {}) or {}
    has_action_mapping = bool(actions)

    methods = _get_view_methods(callback, view_class)
    if not actions:
        actions = {method.lower(): method.lower() for method in methods}

    request_serializers: dict[str, SerializerInfo] = {}
    response_serializers: dict[str, SerializerInfo] = {}
    standard_write_actions = {"create", "update", "partial_update"}

    for method, action_name in actions.items():
        method_name = method.upper()
        action_method = _action_method(view_class, action_name)
        request_class = getattr(
            action_method,
            "api_request_serializer_class",
            None,
        )
        response_class = getattr(
            action_method,
            "api_response_serializer_class",
            None,
        )
        route_class = _resolve_route_serializer_class(
            callback,
            view_class,
            action_name,
        )
        route_is_dynamic = (
            route_class is None
            and hasattr(view_class, "get_serializer_class")
        )
        try:
            from rest_framework.viewsets import ViewSet

            route_is_manual_viewset = (
                route_class is None
                and issubclass(view_class, ViewSet)
            )
        except (ImportError, TypeError):
            route_is_manual_viewset = False
        unresolved_marker = (
            "<dynamic>" if route_is_dynamic else "<viewset>"
        )

        if request_class is None and (
            action_name in standard_write_actions
            or (not has_action_mapping and method_name in {"POST", "PUT", "PATCH"})
        ):
            request_class = route_class
        if response_class is None and action_name != "destroy":
            response_class = route_class

        if request_class is not None:
            name, fields = _inspect_serializer_class(request_class)
            request_serializers[method_name] = SerializerInfo(name=name, fields=fields)
        elif (route_is_dynamic or route_is_manual_viewset) and (
            action_name in standard_write_actions
            or (not has_action_mapping and method_name in {"POST", "PUT", "PATCH"})
        ):
            request_serializers[method_name] = SerializerInfo(
                name=unresolved_marker,
            )
        if response_class is not None:
            name, fields = _inspect_serializer_class(response_class)
            response_serializers[method_name] = SerializerInfo(name=name, fields=fields)
        elif (
            route_is_dynamic or route_is_manual_viewset
        ) and action_name != "destroy":
            response_serializers[method_name] = SerializerInfo(
                name=unresolved_marker,
            )

    return request_serializers, response_serializers


def _primary_serializer(
    serializers_by_method: dict[str, SerializerInfo],
    preferred_methods: tuple[str, ...],
) -> SerializerInfo:
    """Choose a stable representative serializer for legacy consumers."""
    for method in preferred_methods:
        serializer = serializers_by_method.get(method)
        if serializer is not None:
            return serializer
    return next(iter(serializers_by_method.values()), SerializerInfo())


def _permission_names(permission_classes) -> list[str]:
    """Normalize permission classes/instances to class-name strings."""
    if not permission_classes:
        return []
    return [p.__name__ if isinstance(p, type) else type(p).__name__ for p in permission_classes]


def _default_permissions() -> list[str]:
    """Extract DRF default permission class names."""
    from django.conf import settings

    default_perms = (
        getattr(settings, "REST_FRAMEWORK", {}).get("DEFAULT_PERMISSION_CLASSES", [])
    )
    return [p.rsplit(".", 1)[-1] for p in default_perms]


def _get_permissions(callback, view_class) -> tuple[list[str], list[str]]:
    """Extract route-aware permission names for display and write auditing.

    Phase 1.2: Prefers static class-attribute inspection over view
    instantiation.  Only falls back to ``view_class()`` when the class
    overrides ``get_permissions`` with custom logic.
    """
    actions = getattr(callback, "actions", None) or {}
    initkwargs = getattr(callback, "initkwargs", {}) or {}
    route_permission_classes = initkwargs.get("permission_classes")

    if route_permission_classes:
        names = _permission_names(route_permission_classes)
        write_names = names if any(m.upper() in {"POST", "PUT", "PATCH", "DELETE"} for m in actions) else []
        return names, write_names

    base_permissions = _permission_names(getattr(view_class, "permission_classes", None))
    if not base_permissions:
        base_permissions = _default_permissions()

    if not actions or not hasattr(view_class, "get_permissions"):
        write_names = (
            list(base_permissions)
            if any(m.upper() in {"POST", "PUT", "PATCH", "DELETE"} for m in actions)
            else []
        )
        return list(base_permissions), write_names

    # ── Phase 1.2: Check if get_permissions is inherited or overridden ──
    gp_method = getattr(view_class, "get_permissions", None)
    # If get_permissions is the default DRF implementation, we can read
    # permission_classes statically per action without instantiating.
    is_custom = gp_method is not None and "get_permissions" in view_class.__dict__

    if not is_custom:
        # Static path: read permission_classes from class attributes — no instantiation
        # For action-based ViewSets, check per-action permission_classes
        by_method: dict[str, list[str]] = {}
        for method, action in actions.items():
            method_name = method.upper()
            # Check for action-specific permission_classes (e.g. @action(permission_classes=[...]))
            action_perms = None
            if hasattr(view_class, action):
                action_method = getattr(view_class, action)
                if hasattr(action_method, "kwargs"):
                    action_perms = action_method.kwargs.get("permission_classes")
            if action_perms:
                by_method[method_name] = _permission_names(action_perms)
            else:
                by_method[method_name] = list(base_permissions)

        all_permissions = sorted({name for names in by_method.values() for name in names}) or list(
            base_permissions
        )
        write_permissions = sorted(
            {
                name
                for method, names in by_method.items()
                if method in {"POST", "PUT", "PATCH", "DELETE"}
                for name in names
            }
        )
        return all_permissions, write_permissions

    # Fallback: custom get_permissions — must instantiate (rare)
    by_method_fallback: dict[str, list[str]] = {}
    for method, action in actions.items():
        method_name = method.upper()
        try:
            view = view_class()
            view.action = action
            view.request = None
            view.args = ()
            view.kwargs = {}
            by_method_fallback[method_name] = [type(p).__name__ for p in view.get_permissions()]
        except Exception:
            by_method_fallback[method_name] = list(base_permissions)

    all_permissions = sorted({name for names in by_method_fallback.values() for name in names}) or list(
        base_permissions
    )
    write_permissions = sorted(
        {
            name
            for method, names in by_method_fallback.items()
            if method in {"POST", "PUT", "PATCH", "DELETE"}
            for name in names
        }
    )
    return all_permissions, write_permissions


def _get_authentication(view_class) -> list[str]:
    """Extract authentication class names with DRF defaults fallback."""
    auth = getattr(view_class, "authentication_classes", None)
    if auth is not None and auth:
        return [a.__name__ if isinstance(a, type) else type(a).__name__ for a in auth]

    # Fallback to DRF default settings
    from django.conf import settings

    default_auth = (
        getattr(settings, "REST_FRAMEWORK", {}).get("DEFAULT_AUTHENTICATION_CLASSES", [])
    )
    return [a.rsplit(".", 1)[-1] for a in default_auth]


def _get_filter_backends(view_class) -> list[str]:
    """Extract filter backend class names."""
    backends = getattr(view_class, "filter_backends", [])
    if backends:
        return [b.__name__ if isinstance(b, type) else type(b).__name__ for b in backends]

    # Check default settings if missing
    from django.conf import settings
    default_backends = getattr(settings, "REST_FRAMEWORK", {}).get("DEFAULT_FILTER_BACKENDS", [])
    return [b.split(".")[-1] for b in default_backends]


def _get_pagination(view_class) -> str:
    """Extract pagination class name with DRF defaults fallback."""
    pagination = getattr(view_class, "pagination_class", None)
    if pagination:
        return pagination.__name__ if isinstance(pagination, type) else type(pagination).__name__

    # Fallback to DRF default settings
    from django.conf import settings

    default_pagination = (
        getattr(settings, "REST_FRAMEWORK", {}).get("DEFAULT_PAGINATION_CLASS", "")
    )
    if default_pagination:
        return default_pagination.rsplit(".", 1)[-1]
    return ""


def _get_throttle_classes(view_class) -> list[str]:
    """Extract throttle class names."""
    throttles = getattr(view_class, "throttle_classes", [])
    if throttles:
        return [t.__name__ if isinstance(t, type) else type(t).__name__ for t in throttles]

    # Check default settings if missing
    from django.conf import settings
    default_throttles = getattr(settings, "REST_FRAMEWORK", {}).get("DEFAULT_THROTTLE_CLASSES", [])
    return [t.split(".")[-1] for t in default_throttles]


def _get_public_write_controls(callback, view_class) -> list[str]:
    """Return explicitly reviewed controls for intentional public writes."""
    for source in (view_class, callback):
        controls = getattr(source, "audit_public_write_controls", ())
        if controls:
            return [str(control) for control in controls]
    return []


def _get_docstring(view_class, callback) -> str:
    """Extract docstring from view class or callback."""
    # Try view class docstring
    doc = inspect.getdoc(view_class)
    if doc:
        return doc

    # Try callback docstring
    if hasattr(callback, "__doc__") and callback.__doc__:
        return inspect.cleandoc(callback.__doc__)

    return ""


def _extract_action_name(callback) -> str:
    """Try to extract the action name from a ViewSet route."""
    if hasattr(callback, "actions"):
        actions = callback.actions
        if isinstance(actions, dict):
            # Return the most specific action name
            action_names = list(actions.values())
            if action_names:
                return action_names[0]
    if hasattr(callback, "initkwargs"):
        return callback.initkwargs.get("name", "") or callback.initkwargs.get("suffix", "")
    return ""


def _classify_endpoint(path: str, url_params: list[UrlParam] | None = None) -> bool:
    """Check if endpoint is a detail view.

    Supports both Django path converters (<int:pk>) and regex named
    groups ((?P<pk>[^/.]+)).  Also checks resolved url_params for
    common primary-key names.
    """
    # Django path converter at end
    if re.search(r"<\w+(?::\w+)?>/?$", path):
        return True
    # Regex named group at end
    if re.search(r"\(\?P<\w+>[^)]+\)/?\$?$", path):
        return True
    # Check resolved params for PK-like names
    if url_params:
        pk_names = {"pk", "id", "uuid", "slug", "key", "token"}
        if any(p.name in pk_names for p in url_params):
            return True
    return False


def _extract_namespace_from_path(path: str) -> str:
    """Extract a meaningful namespace/group from the URL path."""
    parts = path.strip("/").split("/")

    # API paths: api/v1/section/...
    if len(parts) >= 3 and parts[0] == "api":
        return parts[2] if len(parts) > 2 else parts[1]

    # Direct paths: section/...
    if parts:
        return parts[0]

    return "root"


def _walk_patterns(
    patterns, prefix: str = "", namespace: str = ""
) -> list[tuple[str, Any, str, str]]:
    """Recursively walk URL patterns to collect all endpoints."""
    endpoints = []

    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            # Recurse into nested patterns
            new_prefix = prefix + str(pattern.pattern)
            new_namespace = pattern.namespace or namespace
            endpoints.extend(_walk_patterns(pattern.url_patterns, new_prefix, new_namespace))
        elif isinstance(pattern, URLPattern):
            path = prefix + str(pattern.pattern)
            callback = pattern.callback
            url_name = pattern.name or ""

            # Skip excluded patterns (configurable)
            exclude_patterns = get_setting("EXCLUDE_PATTERNS", [])
            if any(path.startswith(p) for p in exclude_patterns):
                continue

            # Skip format-suffix variants (DRF DefaultRouter duplicates).
            # Every router endpoint gets a .(?P<format>...) variant that is
            # functionally identical — filtering here prevents double-counting
            # in all downstream consumers (audit, search, UI counts).
            if _FORMAT_SUFFIX_RE.search(str(pattern.pattern)):
                continue

            endpoints.append((path, callback, url_name, namespace))

    return endpoints


def _is_drf_view(callback) -> bool:
    """Check if a callback is a DRF view."""
    view_class = _get_view_class(callback)
    if not view_class:
        return False

    try:
        from rest_framework.views import APIView

        return issubclass(view_class, APIView)
    except ImportError:
        return False


def _humanize_name(name: str) -> str:
    """Convert a slug/code name to a human-readable title."""
    # Replace separators
    name = name.replace("_", " ").replace("-", " ")
    # Title case
    return name.title()


# -------------------------------------------------------------------------
# In-memory cache for introspection results
# -------------------------------------------------------------------------
_cache: dict[str, Any] = {"sections": None, "timestamp": 0}
SECTIONS_CACHE_KEY = "mydoc:introspection:sections"


def _invalidate_cache():
    """Force cache invalidation."""
    _cache["sections"] = None
    _cache["timestamp"] = 0
    cache.delete(SECTIONS_CACHE_KEY)
    # Phase 1.4: Invalidate search index alongside section cache
    global _search_index, _search_index_timestamp
    _search_index = None
    _search_index_timestamp = 0.0


def discover_api_endpoints() -> list[SectionInfo]:
    """
    Main entry point: discover all DRF API endpoints and organize them.

    Results are cached in memory for CACHE_TTL seconds (configurable).
    Returns a list of SectionInfo objects, each containing grouped endpoints.

    Phase 1.5: Includes timing instrumentation to measure discovery
    performance and identify bottlenecks.
    """
    # Check cache
    cache_enabled = get_setting("CACHE_ENABLED", True)
    cache_ttl = get_setting("CACHE_TTL", 300)

    if cache_enabled and _cache["sections"] is not None:
        age = time.time() - _cache["timestamp"]
        if age < cache_ttl:
            return _cache["sections"]

    if cache_enabled and cache_ttl > 0:
        cached_sections = cache.get(SECTIONS_CACHE_KEY)
        if cached_sections is not None:
            _cache["sections"] = cached_sections
            _cache["timestamp"] = time.time()
            return cached_sections

    # ── Phase 1.5: Timing instrumentation ──
    t_start = time.monotonic()

    resolver = get_resolver()
    t_resolver = time.monotonic()

    raw_endpoints = _walk_patterns(resolver.url_patterns)
    t_walk = time.monotonic()

    # Filter to allowed methods
    allowed_methods = get_setting("ALLOWED_METHODS", [])
    exclude_namespaces = get_setting("EXCLUDE_NAMESPACES", [])

    # Group collected endpoints by section
    sections_map: dict[str, SectionInfo] = {}

    for path, callback, url_name, namespace in raw_endpoints:
        # Skip excluded namespaces
        if namespace and namespace in exclude_namespaces:
            continue

        # Only include DRF views
        if not _is_drf_view(callback):
            continue

        view_class = _get_view_class(callback)
        if not view_class:
            continue

        # Build endpoint info
        methods = _get_view_methods(callback, view_class)

        # Filter to allowed methods
        if allowed_methods:
            methods = [m for m in methods if m in allowed_methods]
            if not methods:
                continue

        request_serializers, response_serializers = _get_endpoint_serializer_info(
            callback,
            view_class,
        )
        request_serializer = _primary_serializer(
            request_serializers,
            ("POST", "PUT", "PATCH"),
        )
        response_serializer = _primary_serializer(
            response_serializers,
            ("GET", "POST", "PUT", "PATCH", "DELETE"),
        )
        docstring = _get_docstring(view_class, callback)
        action_name = _extract_action_name(callback)

        # Dynamic parameter resolution
        raw_path = f"/{path}" if not path.startswith("/") else path
        url_params = _resolve_url_params(raw_path)
        display_path = _normalize_path(raw_path)
        is_detail = _classify_endpoint(raw_path, url_params)
        intent = _infer_endpoint_intent(
            raw_path, methods, view_class.__name__, action_name, url_params,
        )

        permissions, write_permissions = _get_permissions(callback, view_class)

        endpoint = EndpointInfo(
            path=raw_path,
            methods=methods,
            view_name=url_name,
            view_class=view_class.__name__,
            docstring=docstring,
            description=docstring.split("\n")[0].strip() if docstring else "",
            request_serializer_name=request_serializer.name,
            request_serializer_fields=request_serializer.fields,
            response_serializer_name=response_serializer.name,
            response_serializer_fields=response_serializer.fields,
            request_serializers=request_serializers,
            response_serializers=response_serializers,
            serializer_name=response_serializer.name,
            serializer_fields=response_serializer.fields,
            permissions=permissions,
            write_permissions=write_permissions,
            authentication=_get_authentication(view_class),
            filter_backends=_get_filter_backends(view_class),
            throttle_classes=_get_throttle_classes(view_class),
            public_write_controls=_get_public_write_controls(callback, view_class),
            pagination_class=_get_pagination(view_class),
            url_name=url_name,
            namespace=namespace,
            is_detail=is_detail,
            action_name=action_name,
            url_params=url_params,
            display_path=display_path,
            intent=intent,
        )

        # Determine section name
        section_key = namespace or _extract_namespace_from_path(path)
        if section_key.endswith("-api"):
            section_key = section_key[:-4]

        # Clean up section key
        section_key = section_key.lower().strip()

        if section_key not in sections_map:
            sections_map[section_key] = SectionInfo(
                name=_humanize_name(section_key),
                slug=section_key,
                description=f"API endpoints for {_humanize_name(section_key)}",
                icon=SECTION_ICONS.get(section_key, "server"),
            )

        sections_map[section_key].endpoints.append(endpoint)

    # Sort sections and their endpoints
    sections = sorted(sections_map.values(), key=lambda s: s.name)
    for section in sections:
        section.endpoints.sort(key=lambda e: (e.path, e.methods))

    # ── Phase 1.5: Log discovery timing ──
    t_end = time.monotonic()
    total_ms = (t_end - t_start) * 1000
    walk_ms = (t_walk - t_resolver) * 1000
    inspect_ms = (t_end - t_walk) * 1000
    logger.info(
        "MyDoc discovery: %.1fms total (%d endpoints, %d sections) "
        "[walk=%.1fms, inspect=%.1fms, "
        "serializer_cache=%d, permission_cache=%d]",
        total_ms,
        sum(s.endpoint_count for s in sections),
        len(sections),
        walk_ms,
        inspect_ms,
        len(_serializer_cache),
        len(_permission_cache),
    )

    # Store in cache
    if cache_enabled:
        _cache["sections"] = sections
        _cache["timestamp"] = time.time()
        if cache_ttl > 0:
            cache.set(SECTIONS_CACHE_KEY, sections, timeout=cache_ttl)

    return sections


def get_section_by_slug(slug: str) -> SectionInfo | None:
    """Get a specific section by its slug."""
    sections = discover_api_endpoints()
    for section in sections:
        if section.slug == slug:
            return section
    return None


def get_endpoint_by_slug(section_slug: str, endpoint_slug: str) -> EndpointInfo | None:
    """Get a specific endpoint by section and endpoint slugs."""
    section = get_section_by_slug(section_slug)
    if not section:
        return None
    for ep in section.endpoints:
        if ep.slug == endpoint_slug:
            return ep
    return None


def get_api_stats() -> dict:
    """Get overall API statistics."""
    sections = discover_api_endpoints()
    total_endpoints = sum(s.endpoint_count for s in sections)
    total_methods: dict[str, int] = {}
    for section in sections:
        for ep in section.endpoints:
            for m in ep.methods:
                total_methods[m] = total_methods.get(m, 0) + 1

    return {
        "total_sections": len(sections),
        "total_endpoints": total_endpoints,
        "methods": total_methods,
        "sections": sections,
    }


# =========================================================================
# FROZEN SEARCH INDEX (Phase 1.4)
# =========================================================================


def build_search_index() -> list[dict]:
    """Build or return the frozen search index.

    The index is a flat list of pre-computed search records.  Built once
    per discovery cycle and reused for every search query — avoids
    re-calling ``discover_api_endpoints()`` and re-iterating all
    sections/endpoints on every keystroke.
    """
    global _search_index, _search_index_timestamp

    # Reuse if sections haven't changed
    sections_timestamp = _cache.get("timestamp", 0)
    if (
        _search_index is not None
        and _search_index_timestamp == sections_timestamp
    ):
        return _search_index

    sections = discover_api_endpoints()
    index: list[dict] = []

    for section in sections:
        section_name_lower = section.name.lower()
        section_slug = section.slug
        section_icon = section.icon

        for ep in section.endpoints:
            display = ep.display_path or ep.path
            index.append({
                # Pre-computed lowercase fields for fast comparison
                "section_name": section.name,
                "section_slug": section_slug,
                "section_icon": section_icon,
                "endpoint_path": display,
                "endpoint_slug": ep.slug,
                "endpoint_methods": ep.methods,
                "endpoint_description": ep.short_description,
                "view_class": ep.view_class,
                "intent": ep.intent.value,
                # Pre-lowered search corpus
                "_path_lower": display.lower(),
                "_raw_path_lower": ep.path.lower(),
                "_view_class_lower": ep.view_class.lower(),
                "_docstring_lower": (ep.docstring or "").lower(),
                "_view_name_lower": ep.view_name.lower(),
                "_section_name_lower": section_name_lower,
                "_methods_lower": [m.lower() for m in ep.methods],
            })

    _search_index = index
    _search_index_timestamp = sections_timestamp
    return index
