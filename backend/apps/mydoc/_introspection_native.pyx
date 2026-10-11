# cython: language_level=3, boundscheck=False, wraparound=False, cdivision=True
"""
MyDoc Introspection — Cython Native Acceleration Module (Phase 2)

Provides C-compiled versions of the hottest introspection functions:
  - normalize_path_native:    Single-pass string builder replacing 4 regex ops
  - resolve_url_params_native: Typed regex result handling for URL params
  - search_native:            Flat index scan with typed string comparison
  - build_openapi_paths_native: Pre-allocated dict construction for spec

Fallback: If Cython is not installed, the pure-Python versions in
introspection.py are used transparently via try/except ImportError.

..  IMPORTANT — Dual-maintenance requirement:
    The Cython implementations in this file are mirrored by pure-Python
    fallback implementations in ``_native.py``.  Any change to function
    signatures, logic, or performance characteristics must be applied to
    **both** files.  Keep the two implementations in sync to avoid divergence
    between native and fallback code paths.
"""

import re
from typing import Any

# Pre-compiled regex patterns (compiled once at module load)
cdef object _RE_ANCHORS = re.compile(r"[\^$]")
cdef object _RE_MULTI_SLASH = re.compile(r"/+")

# Type mapping for URL params
_REGEX_TYPE_MAP = {
    b"[0-9]+": "int",
    b"\\d+": "int",
    b"[^/.]+": "str",
    b"[\\w-]+": "slug",
    b"[0-9a-f-]{36}": "uuid",
    b"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}": "uuid",
}

# Python-level pattern objects for URL param extraction
cdef object _PATH_CONVERTER_RE = re.compile(r"<(?:(?P<type>\w+):)?(?P<name>\w+)>")
cdef object _REGEX_NAMED_GROUP_RE = re.compile(r"\(\?P<(?P<name>\w+)>[^)]+\)")


def normalize_path_native(str raw_path) -> str:
    """Cython-accelerated path normalization.

    Replaces the 4-regex _normalize_path with a single-pass approach:
    1. Replace regex named groups with {name} or {name:type}
    2. Replace path converters with {name} or {name:type}
    3. Strip anchors and normalize slashes
    """
    cdef str path = raw_path

    # Step 1: Replace regex named groups (?P<name>pattern) → {name} or {name:type}
    path = _REGEX_NAMED_GROUP_RE.sub(_regex_to_placeholder, path)

    # Step 2: Replace path converters <type:name> → {name:type}
    path = _PATH_CONVERTER_RE.sub(_converter_to_placeholder, path)

    # Step 3: Strip regex anchors
    path = _RE_ANCHORS.sub("", path)

    # Step 4: Normalize slashes in single pass
    parts = path.split("/")
    filtered = []
    for p in parts:
        if p:
            filtered.append(p)
    path = "/" + "/".join(filtered) + "/"

    return path


cdef str _regex_to_placeholder(object match):
    """Convert a regex named group match to a {name} or {name:type} placeholder."""
    cdef str name = match.group("name")
    cdef str full = match.group(0)
    cdef str inner = full.split(">", 1)[-1].rstrip(")")
    cdef str pattern_str, ptype

    for pattern_str, ptype in _REGEX_TYPE_MAP.items():
        if pattern_str.decode() in inner:
            return f"{{{name}:{ptype}}}"
    return f"{{{name}}}"


cdef str _converter_to_placeholder(object match):
    """Convert a Django path converter match to a {name} or {name:type} placeholder."""
    cdef str name = match.group("name")
    cdef str ptype = match.group("type")
    if ptype and ptype != "str":
        return f"{{{name}:{ptype}}}"
    return f"{{{name}}}"


def resolve_url_params_native(str raw_path) -> list:
    """Cython-accelerated URL parameter extraction.

    Returns a list of dicts with name, param_type, required, pattern keys.
    Avoids creating UrlParam dataclass instances for intermediate processing.
    """
    cdef list params = []
    cdef set seen = set()
    cdef str name, param_type, full_match, inner
    cdef object m

    # Django path converters: <int:pk>, <slug>, etc.
    for m in _PATH_CONVERTER_RE.finditer(raw_path):
        name = m.group("name")
        param_type = m.group("type") or "str"
        if name not in seen:
            seen.add(name)
            params.append({
                "name": name,
                "param_type": param_type,
                "required": True,
                "pattern": "",
            })

    # Regex named groups: (?P<pk>[^/.]+)
    for m in _REGEX_NAMED_GROUP_RE.finditer(raw_path):
        name = m.group("name")
        if name in seen or name == "format":
            continue
        seen.add(name)

        full_match = m.group(0)
        inner = full_match.split(">", 1)[-1].rstrip(")")
        param_type = "str"
        for pattern_str, ptype in _REGEX_TYPE_MAP.items():
            if pattern_str.decode() in inner:
                param_type = ptype
                break
        params.append({
            "name": name,
            "param_type": param_type,
            "required": True,
            "pattern": inner,
        })

    return params


def search_native(list index, str query) -> list:
    """Cython-accelerated flat index search.

    Scans the frozen search index with typed string operations.
    All comparison fields are pre-lowered at index build time.
    """
    cdef list results = []
    cdef dict record
    cdef int score
    cdef str m_lower
    cdef list methods_lower

    for record in index:
        score = 0
        if query in record["_path_lower"]:
            score += 10
        if query in record["_raw_path_lower"]:
            score += 5
        if query in record["_view_class_lower"]:
            score += 5
        if query in record["_docstring_lower"]:
            score += 3
        if query in record["_view_name_lower"]:
            score += 5
        if query in record["_section_name_lower"]:
            score += 2

        methods_lower = record["_methods_lower"]
        for m_lower in methods_lower:
            if query == m_lower:
                score += 8

        if score > 0:
            results.append({
                "section_name": record["section_name"],
                "section_slug": record["section_slug"],
                "section_icon": record["section_icon"],
                "endpoint_path": record["endpoint_path"],
                "endpoint_slug": record["endpoint_slug"],
                "endpoint_methods": record["endpoint_methods"],
                "endpoint_description": record["endpoint_description"],
                "view_class": record["view_class"],
                "intent": record["intent"],
                "score": score,
            })

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:50]


def build_openapi_paths_native(list sections) -> dict:
    """Cython-accelerated OpenAPI paths dict construction.

    Pre-allocates the paths dict and builds operations with minimal
    intermediate allocations.  Returns {"paths": dict, "tags": list}.
    """
    cdef dict paths = {}
    cdef list tags = []
    cdef dict section_dict, ep_dict, operation, param_schema, schema, param
    cdef list params_list, required_fields
    cdef str path_key, method_lower
    cdef str f_name, f_type, f_help, prop_type
    cdef dict prop, properties
    cdef object f

    for section in sections:
        tags.append({
            "name": section["name"],
            "description": section.get("description", ""),
        })

        for ep in section.get("endpoints", []):
            path_key = ep.get("display_path") or ep.get("path", "")
            if path_key not in paths:
                paths[path_key] = {}

            for method in ep.get("methods", []):
                method_lower = method.lower()
                operation = {
                    "tags": [section["name"]],
                    "summary": ep.get("short_description") or ep.get("view_name") or ep.get("view_class", ""),
                    "operationId": f"{section['slug']}_{ep['slug']}_{method_lower}",
                    "responses": {
                        "200": {"description": "Successful response"},
                        "400": {"description": "Bad request"},
                        "401": {"description": "Unauthorized"},
                        "403": {"description": "Forbidden"},
                        "404": {"description": "Not found"},
                    },
                }

                docstring = ep.get("docstring")
                if docstring:
                    operation["description"] = docstring

                authentication = ep.get("authentication")
                if authentication:
                    operation["security"] = [{auth: [] for auth in authentication}]

                # Request body for write methods
                serializer_fields = (
                    ep.get("request_serializer_fields")
                    or ep.get("serializer_fields")
                )
                if method_lower in ("post", "put", "patch") and serializer_fields:
                    properties = {}
                    required_fields = []

                    for f in serializer_fields:
                        if f.get("read_only"):
                            continue
                        prop = {"type": _field_type_to_openapi_native(f.get("field_type", ""))}
                        if f.get("help_text"):
                            prop["description"] = f["help_text"]
                        if f.get("max_length"):
                            prop["maxLength"] = f["max_length"]
                        if f.get("choices"):
                            prop["enum"] = f["choices"]
                        properties[f["name"]] = prop
                        if f.get("required"):
                            required_fields.append(f["name"])

                    schema = {"type": "object", "properties": properties}
                    if required_fields:
                        schema["required"] = required_fields
                    operation["requestBody"] = {
                        "required": True,
                        "content": {"application/json": {"schema": schema}},
                    }

                # Path parameters
                url_params = ep.get("url_params")
                if url_params:
                    params_list = []
                    for p in url_params:
                        p_type = p.get("param_type", "str")
                        if p_type == "int":
                            param_schema = {"type": "integer"}
                        elif p_type == "uuid":
                            param_schema = {"type": "string", "format": "uuid"}
                        else:
                            param_schema = {"type": "string"}
                        params_list.append({
                            "name": p["name"],
                            "in": "path",
                            "required": p.get("required", True),
                            "schema": param_schema,
                        })
                    if params_list:
                        operation["parameters"] = params_list

                paths[path_key][method_lower] = operation

    return {"paths": paths, "tags": tags}


# Field type → OpenAPI type mapping as a dict for fast lookup
_OPENAPI_TYPE_MAP = {
    "CharField": "string",
    "TextField": "string",
    "IntegerField": "integer",
    "FloatField": "number",
    "DecimalField": "string",
    "BooleanField": "boolean",
    "DateField": "string",
    "DateTimeField": "string",
    "TimeField": "string",
    "EmailField": "string",
    "URLField": "string",
    "UUIDField": "string",
    "IPAddressField": "string",
    "FileField": "string",
    "ImageField": "string",
    "SlugField": "string",
    "JSONField": "object",
    "DictField": "object",
    "ListField": "array",
    "PrimaryKeyRelatedField": "integer",
    "ChoiceField": "string",
}


cdef str _field_type_to_openapi_native(str field_type):
    """Fast Cython-typed OpenAPI type lookup."""
    return _OPENAPI_TYPE_MAP.get(field_type, "string")
