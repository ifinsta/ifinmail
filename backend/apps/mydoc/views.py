"""
MyDoc Views

Renders the auto-generated API documentation pages.
Includes: index, section, endpoint detail, search, OpenAPI export,
and cache management.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.views.generic import TemplateView, View

from ._native import search_native as _search_native
from .auditor import AuditReport, generate_report, get_endpoint_findings, run_audit
from .config import get_config, get_setting
from .introspection import (
    FieldInfo,
    SectionInfo,
    _invalidate_cache,
    build_search_index,
    discover_api_endpoints,
    get_api_stats,
    get_endpoint_by_slug,
    get_section_by_slug,
)

logger = logging.getLogger(__name__)


# =========================================================================
# MIXINS
# =========================================================================


class MyDocConfigMixin:
    """Injects mydoc configuration into every template context."""

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        config = get_config()
        context["mydoc_config"] = config
        context["playground_enabled"] = config.get("PLAYGROUND_ENABLED", True)
        context["openapi_enabled"] = config.get("OPENAPI_ENABLED", True)
        context["code_snippets"] = config.get("CODE_SNIPPETS", ["curl", "python", "javascript"])
        context["environments"] = config.get("ENVIRONMENTS", [])
        context["mydoc_title"] = config.get("TITLE", "API Documentation")
        context["mydoc_description"] = config.get("DESCRIPTION", "Auto-generated from live endpoints.")
        context["mydoc_logo"] = config.get("LOGO_TEXT", "MyDoc")
        return context


# =========================================================================
# PAGE VIEWS
# =========================================================================


class MyDocIndexView(MyDocConfigMixin, TemplateView):
    """Landing page for API documentation -- shows all sections as cards."""

    template_name = "mydoc/index.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        stats = get_api_stats()
        context["sections"] = stats["sections"]
        context["total_endpoints"] = stats["total_endpoints"]
        context["total_sections"] = stats["total_sections"]
        context["method_counts"] = stats["methods"]
        return context


class MyDocSectionView(MyDocConfigMixin, TemplateView):
    """Section page -- lists all endpoints within an API section."""

    template_name = "mydoc/section.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        slug = self.kwargs.get("section_slug", "")
        section = get_section_by_slug(slug)
        all_sections = discover_api_endpoints()

        context["section"] = section
        context["sections"] = all_sections
        context["current_slug"] = slug
        return context


class MyDocEndpointView(MyDocConfigMixin, TemplateView):
    """Endpoint detail page -- shows full details for a single endpoint."""

    template_name = "mydoc/endpoint.html"

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        section_slug = self.kwargs.get("section_slug", "")
        endpoint_slug = self.kwargs.get("endpoint_slug", "")
        endpoint = get_endpoint_by_slug(section_slug, endpoint_slug)

        if endpoint is None and endpoint_slug.startswith("api-v1-base-"):
            canonical_slug = endpoint_slug.replace("api-v1-base-", "api-v1-", 1)
            if get_endpoint_by_slug(section_slug, canonical_slug) is not None:
                return redirect(
                    "mydoc:endpoint",
                    section_slug=section_slug,
                    endpoint_slug=canonical_slug,
                )

        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        section_slug = self.kwargs.get("section_slug", "")
        endpoint_slug = self.kwargs.get("endpoint_slug", "")

        section = get_section_by_slug(section_slug)
        endpoint = get_endpoint_by_slug(section_slug, endpoint_slug)
        all_sections = discover_api_endpoints()

        # Audit findings for this endpoint
        if endpoint:
            endpoint_findings = get_endpoint_findings(endpoint.path)
            context["audit_findings"] = endpoint_findings
            context["audit_critical"] = sum(
                1 for f in endpoint_findings if f.severity.value == "critical"
            )
            context["audit_warning"] = sum(
                1 for f in endpoint_findings if f.severity.value == "warning"
            )

        context["section"] = section
        context["endpoint"] = endpoint
        context["sections"] = all_sections
        context["current_section_slug"] = section_slug
        context["current_endpoint_slug"] = endpoint_slug

        # Serializer field metadata as JSON for the playground
        if endpoint and (
            endpoint.request_serializer_fields
            or endpoint.response_serializer_fields
            or endpoint.serializer_fields
        ):
            request_example = {}
            response_example = {}
            fields_meta = []

            request_fields = (
                endpoint.request_serializer_fields
                or endpoint.serializer_fields
            )
            response_fields = (
                endpoint.response_serializer_fields
                or endpoint.serializer_fields
            )

            for f in request_fields:
                example_value = _get_example_value(f)
                if not f.read_only:
                    request_example[f.name] = example_value

            for f in response_fields:
                example_value = _get_example_value(f)
                if f.write_only:
                    continue
                response_example[f.name] = example_value

                fields_meta.append(
                    {
                        "name": f.name,
                        "type": f.field_type,
                        "required": f.required,
                        "read_only": f.read_only,
                        "write_only": f.write_only,
                        "help_text": f.help_text,
                        "max_length": f.max_length,
                        "choices": f.choices,
                        "default": f.default,
                        "example": example_value,
                    }
                )

            context["request_example"] = json.dumps(request_example, indent=2)
            context["response_example"] = json.dumps(response_example, indent=2)
            context["fields_meta_json"] = json.dumps(fields_meta)
        else:
            context["fields_meta_json"] = "[]"

        # Endpoint metadata for playground JS
        if endpoint:
            context["endpoint_meta_json"] = json.dumps(
                {
                    "path": endpoint.display_path or endpoint.path,
                    "methods": endpoint.methods,
                    "authentication": endpoint.authentication,
                    "permissions": endpoint.permissions,
                    "serializer_name": endpoint.serializer_name,
                    "request_serializer_name": endpoint.request_serializer_name,
                    "response_serializer_name": endpoint.response_serializer_name,
                    "url_params": [
                        {"name": p.name, "type": p.param_type, "required": p.required}
                        for p in endpoint.url_params
                    ],
                    "intent": endpoint.intent.value,
                }
            )
        else:
            context["endpoint_meta_json"] = "{}"

        return context


class MyDocSearchView(MyDocConfigMixin, TemplateView):
    """Search across all API docs -- returns JSON for AJAX or rendered page."""

    template_name = "mydoc/search.html"

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        query = request.GET.get("q", "").strip().lower()

        if (
            request.headers.get("X-Requested-With") == "XMLHttpRequest"
            or request.GET.get("format") == "json"
        ):
            return self._json_search(query)

        context = self.get_context_data(**kwargs)
        context["query"] = query
        if query:
            context["results"] = self._search(query)
        return self.render_to_response(context)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["sections"] = discover_api_endpoints()
        return context

    def _search(self, query: str) -> list[dict]:
        """Search endpoints by query string using frozen index.

        Phase 1.4: Uses the pre-built search index instead of
        re-discovering all endpoints on every search request.
        Phase 2.6: Uses Cython-accelerated search_native when available.
        """
        index = build_search_index()

        # Phase 2.6: Use native-accelerated search (Cython or optimized Python)
        return _search_native(index, query)

    def _json_search(self, query: str) -> JsonResponse:
        """Return search results as JSON."""
        if not query:
            return JsonResponse({"results": []})
        results = self._search(query)
        return JsonResponse({"results": results})


# =========================================================================
# API VIEWS
# =========================================================================


class MyDocOpenAPIView(View):
    """
    Generates an OpenAPI 3.0 specification from introspected endpoints.

    Accessible at /mydoc/openapi.json
    """

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        config = get_config()

        if not config.get("OPENAPI_ENABLED", True):
            return JsonResponse({"error": "OpenAPI export is disabled"}, status=403)

        base_url = config.get("BASE_URL") or f"{request.scheme}://{request.get_host()}"
        sections = discover_api_endpoints()

        spec = self._build_spec(sections, config, base_url)
        return JsonResponse(spec, json_dumps_params={"indent": 2})

    def _build_spec(self, sections: list[SectionInfo], config: dict[str, Any], base_url: str) -> dict[str, Any]:
        """Build the OpenAPI 3.0 spec dict."""
        paths = {}
        tags = []

        for section in sections:
            tags.append(
                {
                    "name": section.name,
                    "description": section.description,
                }
            )

            for ep in section.endpoints:
                # Use clean display_path for OpenAPI path keys
                path_key = ep.display_path or ep.path
                if path_key not in paths:
                    paths[path_key] = {}

                for method in ep.methods:
                    method_lower = method.lower()
                    request_serializer = ep.request_serializer_for(method)
                    response_serializer = ep.response_serializer_for(method)
                    operation = {
                        "tags": [section.name],
                        "summary": ep.short_description or ep.view_name or ep.view_class,
                        "operationId": f"{section.slug}_{ep.slug}_{method_lower}",
                        "responses": {
                            "200": {"description": "Successful response"},
                            "400": {"description": "Bad request"},
                            "401": {"description": "Unauthorized"},
                            "403": {"description": "Forbidden"},
                            "404": {"description": "Not found"},
                        },
                    }

                    if ep.docstring:
                        operation["description"] = ep.docstring

                    # Security schemes
                    if ep.authentication:
                        operation["security"] = [{auth: [] for auth in ep.authentication}]

                    # Request body for write methods
                    if (
                        method_lower in ("post", "put", "patch")
                        and request_serializer.fields
                    ):
                        properties = {}
                        required_fields = []

                        for f in request_serializer.fields:
                            if f.read_only:
                                continue
                            prop = {"type": _field_type_to_openapi(f.field_type)}
                            if f.help_text:
                                prop["description"] = f.help_text
                            if f.max_length:
                                prop["maxLength"] = f.max_length
                            if f.choices:
                                prop["enum"] = f.choices
                            properties[f.name] = prop

                            if f.required:
                                required_fields.append(f.name)

                        schema = {"type": "object", "properties": properties}
                        if required_fields:
                            schema["required"] = required_fields

                        operation["requestBody"] = {
                            "required": True,
                            "content": {"application/json": {"schema": schema}},
                        }

                    if response_serializer.fields:
                        response_properties = {}
                        for f in response_serializer.fields:
                            if f.write_only:
                                continue
                            prop = {"type": _field_type_to_openapi(f.field_type)}
                            if f.help_text:
                                prop["description"] = f.help_text
                            if f.choices:
                                prop["enum"] = f.choices
                            response_properties[f.name] = prop

                        operation["responses"]["200"]["content"] = {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": response_properties,
                                }
                            }
                        }

                    # Path parameters from resolved url_params
                    if ep.url_params:
                        params = []
                        for p in ep.url_params:
                            param_schema = {"type": "string"}
                            if p.param_type == "int":
                                param_schema = {"type": "integer"}
                            elif p.param_type == "uuid":
                                param_schema = {"type": "string", "format": "uuid"}
                            params.append(
                                {
                                    "name": p.name,
                                    "in": "path",
                                    "required": p.required,
                                    "schema": param_schema,
                                }
                            )
                        if params:
                            operation.setdefault("parameters", []).extend(params)

                    paths[path_key][method_lower] = operation

        return {
            "openapi": config.get("OPENAPI_VERSION", "3.0.3"),
            "info": {
                "title": config.get("TITLE", "API Documentation"),
                "description": config.get("DESCRIPTION", ""),
                "version": "1.0.0",
            },
            "servers": [{"url": base_url}],
            "tags": tags,
            "paths": paths,
        }


class MyDocCacheInvalidateView(View):
    """Invalidates the introspection cache. POST only."""

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        _invalidate_cache()
        return JsonResponse({"status": "ok", "message": "Cache invalidated"})


# =========================================================================
# HELPERS
# =========================================================================


def _get_example_value(field_info: FieldInfo) -> Any:
    """Generate an example value based on field type."""
    type_map = {
        "CharField": "string",
        "TextField": "string",
        "IntegerField": 0,
        "FloatField": 0.0,
        "DecimalField": "0.00",
        "BooleanField": True,
        "DateField": "2026-01-01",
        "DateTimeField": "2026-01-01T00:00:00Z",
        "TimeField": "12:00:00",
        "EmailField": "user@example.com",
        "URLField": "https://example.com",
        "UUIDField": "550e8400-e29b-41d4-a716-446655440000",
        "IPAddressField": "127.0.0.1",
        "FileField": "file.pdf",
        "ImageField": "image.png",
        "SlugField": "example-slug",
        "JSONField": {},
        "DictField": {},
        "ListField": [],
        "PrimaryKeyRelatedField": 1,
        "StringRelatedField": "related_object",
        "SerializerMethodField": None,
        "HiddenField": None,
        "ReadOnlyField": None,
        "ChoiceField": field_info.choices[0] if field_info.choices else "option",
    }
    return type_map.get(field_info.field_type, "value")


def _field_type_to_openapi(field_type: str) -> str:
    """Map DRF field types to OpenAPI types."""
    mapping = {
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
    return mapping.get(field_type, "string")


# =========================================================================
# AUDIT VIEW
# =========================================================================


class MyDocAuditView(MyDocConfigMixin, TemplateView):
    """API Audit Dashboard — proactive quality checks for developers."""

    template_name = "mydoc/audit.html"

    @staticmethod
    def _build_sidebar_sections(sections: list[SectionInfo], report: AuditReport) -> list[dict[str, Any]]:
        sidebar_sections = []
        for section in sections:
            findings = report.findings_for_section(section.slug)
            sidebar_sections.append(
                {
                    "slug": section.slug,
                    "name": section.name,
                    "icon": section.icon,
                    "endpoint_count": section.endpoint_count,
                    "finding_count": len(findings),
                }
            )

        if report.findings:
            return [section for section in sidebar_sections if section["finding_count"]]

        return sorted(
            sidebar_sections,
            key=lambda section: (-section["endpoint_count"], section["name"]),
        )

    def _build_audit_payload(self) -> tuple[list[SectionInfo], AuditReport]:
        sections = discover_api_endpoints()
        report = run_audit(sections)
        return sections, report

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        # Support JSON export
        if request.GET.get("format") == "json":
            _sections, report = self._build_audit_payload()
            return JsonResponse(
                {
                    "score": report.score,
                    "grade": report.grade,
                    "sections_audited": report.sections_audited,
                    "endpoints_audited": report.endpoints_audited,
                    "critical": report.critical_count,
                    "warnings": report.warning_count,
                    "info": report.info_count,
                    "summary": report.summary_by_rule(),
                    "findings": [f.to_dict() for f in report.findings],
                }
            )
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        sections, report = self._build_audit_payload()
        context["report"] = report
        context["sections"] = sections
        context["summary_by_rule"] = report.summary_by_rule()
        context["audit_sidebar_sections"] = self._build_sidebar_sections(sections, report)

        # Filter support
        severity_filter = self.request.GET.get("severity", "")
        rule_filter = self.request.GET.get("rule", "")

        filtered = report.findings
        if severity_filter:
            filtered = [f for f in filtered if f.severity.value == severity_filter]
        if rule_filter:
            filtered = [f for f in filtered if f.rule_id == rule_filter]

        context["filtered_findings"] = filtered
        context["active_severity"] = severity_filter
        context["active_rule"] = rule_filter
        return context


class MyDocReportView(View):
    """Generate and serve the Markdown audit report file."""

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        output_path = generate_report()
        return JsonResponse(
            {
                "status": "ok",
                "message": "Report generated",
                "path": output_path,
            }
        )
