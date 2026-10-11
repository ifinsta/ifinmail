"""
MyDoc Introspection — Native Acceleration Interface (Phase 2.6)

Provides a unified import interface that tries the Cython-compiled native
module first, and falls back to pure-Python implementations transparently.

Usage:
    from backend.apps.core.mydoc._native import normalize_path_native

All functions have identical signatures whether Cython or pure-Python.

..  IMPORTANT — Dual-maintenance requirement:
    The pure-Python fallback implementations in this file mirror the Cython
    implementations in ``_introspection_native.pyx``.  Any change to function
    signatures, logic, or performance characteristics must be applied to
    **both** files.  Keep the two implementations in sync to avoid divergence
    between native and fallback code paths.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Try importing Cython-compiled native module
# ---------------------------------------------------------------------------
try:
    from ._introspection_native import (  # type: ignore[no-redef]
        build_openapi_paths_native,
        normalize_path_native,
        resolve_url_params_native,
        search_native,
    )

    _NATIVE_AVAILABLE = True
except ImportError:
    _NATIVE_AVAILABLE = False

    # -----------------------------------------------------------------------
    # Pure-Python fallbacks (identical signatures)
    # -----------------------------------------------------------------------
    _PATH_CONVERTER_RE = re.compile(r"<(?:(?P<type>\w+):)?(?P<name>\w+)>")
    _REGEX_NAMED_GROUP_RE = re.compile(r"\(\?P<(?P<name>\w+)>[^)]+\)")
    _REGEX_NOISE_RE = re.compile(r"[\^$]")
    _REGEX_TYPE_MAP = {
        r"[0-9]+": "int",
        r"\d+": "int",
        r"[^/.]+": "str",
        r"[\w-]+": "slug",
        r"[0-9a-f-]{36}": "uuid",
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}": "uuid",
    }

    def normalize_path_native(raw_path: str) -> str:
        """Pure-Python fallback for normalize_path."""
        path = raw_path

        def _regex_to_placeholder(m: re.Match) -> str:
            name = m.group("name")
            full = m.group(0)
            inner = full.split(">", 1)[-1].rstrip(")")
            for pattern, ptype in _REGEX_TYPE_MAP.items():
                if pattern in inner:
                    return f"{{{name}:{ptype}}}"
            return f"{{{name}}}"

        path = _REGEX_NAMED_GROUP_RE.sub(_regex_to_placeholder, path)

        def _converter_to_placeholder(m: re.Match) -> str:
            name = m.group("name")
            ptype = m.group("type")
            if ptype and ptype != "str":
                return f"{{{name}:{ptype}}}"
            return f"{{{name}}}"

        path = _PATH_CONVERTER_RE.sub(_converter_to_placeholder, path)
        path = _REGEX_NOISE_RE.sub("", path)

        # Single-pass slash normalization instead of re.sub
        parts = path.split("/")
        filtered = [p for p in parts if p]
        path = "/" + "/".join(filtered) + "/"

        return path

    def resolve_url_params_native(raw_path: str) -> list:
        """Pure-Python fallback for resolve_url_params."""
        params = []
        seen = set()

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

        for m in _REGEX_NAMED_GROUP_RE.finditer(raw_path):
            name = m.group("name")
            if name in seen or name == "format":
                continue
            seen.add(name)
            full_match = m.group(0)
            inner = full_match.split(">", 1)[-1].rstrip(")")
            param_type = "str"
            for pattern, ptype in _REGEX_TYPE_MAP.items():
                if pattern in inner:
                    param_type = ptype
                    break
            params.append({
                "name": name,
                "param_type": param_type,
                "required": True,
                "pattern": inner,
            })

        return params

    def search_native(index: list, query: str) -> list:
        """Pure-Python fallback for search_native."""
        results = []

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
            for m_lower in record["_methods_lower"]:
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

    def build_openapi_paths_native(sections: list) -> dict:
        """Pure-Python fallback for build_openapi_paths_native."""
        paths = {}
        tags = []

        _OPENAPI_TYPE_MAP = {
            "CharField": "string", "TextField": "string",
            "IntegerField": "integer", "FloatField": "number",
            "DecimalField": "string", "BooleanField": "boolean",
            "DateField": "string", "DateTimeField": "string",
            "TimeField": "string", "EmailField": "string",
            "URLField": "string", "UUIDField": "string",
            "IPAddressField": "string", "FileField": "string",
            "ImageField": "string", "SlugField": "string",
            "JSONField": "object", "DictField": "object",
            "ListField": "array", "PrimaryKeyRelatedField": "integer",
            "ChoiceField": "string",
        }

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
                            prop = {"type": _OPENAPI_TYPE_MAP.get(f.get("field_type", ""), "string")}
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


def is_native_available() -> bool:
    """Check if Cython-compiled native module is loaded."""
    return _NATIVE_AVAILABLE
