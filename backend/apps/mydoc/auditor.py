"""
MyDoc API Auditor

Proactive quality checks across all documented API endpoints.
Identifies common pitfalls: missing pagination, weak auth, no docs,
unbounded responses, validation gaps, and more.

Uses dynamic endpoint intent classification to avoid false positives:
checks are applied only to endpoints whose semantic role matches
(e.g., UNBOUNDED_LIST only fires for LIST-intent endpoints).

Each check produces AuditFinding objects with severity, description,
and actionable recommendations.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime

from .introspection import (
    EndpointInfo,
    SectionInfo,
    SerializerInfo,
    discover_api_endpoints,
)
from .types import EndpointIntent, Severity

# =========================================================================
# PRE-COMPILED AUDIT REGEX (Phase 1.3 — combined alternation patterns)
# =========================================================================

_VERB_PATTERN = re.compile(
    r"(?:"
    r"/get[_-]|"
    r"/create[_-]|"
    r"/update[_-]|"
    r"/delete[_-]|"
    r"/fetch[_-]|"
    r"/remove[_-]|"
    r"/add[_-]"
    r")"
)


# =========================================================================
# DATA STRUCTURES
# =========================================================================


SEVERITY_WEIGHT = {
    Severity.CRITICAL: 10,
    Severity.WARNING: 2,
    Severity.INFO: 0,
}


@dataclass
class AuditFinding:
    """A single audit finding for an endpoint or section."""

    rule_id: str
    severity: Severity
    title: str
    description: str
    recommendation: str
    endpoint_path: str = ""
    section_name: str = ""
    section_slug: str = ""
    endpoint_slug: str = ""
    logical_key: str = ""
    affected_endpoint_paths: list[str] = field(default_factory=list)
    affected_methods: list[str] = field(default_factory=list)
    serializer_name: str = ""

    @property
    def severity_label(self) -> str:
        return self.severity.value.upper()

    @property
    def icon(self) -> str:
        return {
            Severity.CRITICAL: "alert-triangle",
            Severity.WARNING: "alert-circle",
            Severity.INFO: "info",
        }.get(self.severity, "info")

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity.value,
            "title": self.title,
            "description": self.description,
            "recommendation": self.recommendation,
            "endpoint_path": self.endpoint_path,
            "section_name": self.section_name,
            "section_slug": self.section_slug,
            "endpoint_slug": self.endpoint_slug,
            "affected_methods": self.affected_methods,
            "serializer_name": self.serializer_name,
            "affected_endpoint_paths": self.affected_endpoint_paths
            or ([self.endpoint_path] if self.endpoint_path else []),
        }

    @property
    def affected_endpoint_count(self) -> int:
        return len(
            self.affected_endpoint_paths
            or ([self.endpoint_path] if self.endpoint_path else [])
        )


@dataclass
class AuditReport:
    """Full audit report across all API sections."""

    findings: list[AuditFinding] = field(default_factory=list)
    sections_audited: int = 0
    endpoints_audited: int = 0

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.CRITICAL)

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.WARNING)

    @property
    def info_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.INFO)

    @property
    def score(self) -> int:
        """
        API health score (0-100).

        Deducts the worst severity per unique endpoint (not per-finding),
        so an endpoint with 5 warnings only deducts 2 points, not 10.
        Total deductions are capped at 80 so large projects still get
        a readable baseline score of at least 20.
        """
        # Group findings by endpoint, take the worst severity per endpoint
        per_endpoint: dict[str, int] = {}
        for f in self.findings:
            key = f.endpoint_path
            weight = SEVERITY_WEIGHT[f.severity]
            per_endpoint[key] = max(per_endpoint.get(key, 0), weight)

        deductions = min(sum(per_endpoint.values()), 80)
        raw = max(0, 100 - deductions)
        if self.critical_count:
            # A report with an unresolved critical issue cannot be graded A.
            raw = min(raw, 89)
        return max(0, min(100, raw))

    @property
    def grade(self) -> str:
        s = self.score
        if s >= 90:
            return "A"
        if s >= 80:
            return "B"
        if s >= 70:
            return "C"
        if s >= 60:
            return "D"
        return "F"

    @property
    def grade_color(self) -> str:
        return {
            "A": "#10b981",
            "B": "#3b82f6",
            "C": "#f59e0b",
            "D": "#f97316",
            "F": "#ef4444",
        }.get(self.grade, "#6b7280")

    def findings_for_endpoint(self, endpoint_path: str) -> list[AuditFinding]:
        return [
            finding
            for finding in self.findings
            if endpoint_path
            in (
                finding.affected_endpoint_paths
                or [finding.endpoint_path]
            )
        ]

    def findings_for_section(self, section_slug: str) -> list[AuditFinding]:
        return [f for f in self.findings if f.section_slug == section_slug]

    def findings_by_rule(self) -> dict[str, list[AuditFinding]]:
        grouped: dict[str, list[AuditFinding]] = {}
        for f in self.findings:
            grouped.setdefault(f.rule_id, []).append(f)
        return grouped

    def summary_by_rule(self) -> list[dict]:
        """Return a summary list grouped by rule, sorted by severity."""
        by_rule = self.findings_by_rule()
        summary = []
        for rule_id, findings in by_rule.items():
            summary.append(
                {
                    "rule_id": rule_id,
                    "title": findings[0].title,
                    "severity": findings[0].severity.value,
                    "count": len(findings),
                    "affected_endpoint_count": sum(
                        finding.affected_endpoint_count for finding in findings
                    ),
                    "recommendation": findings[0].recommendation,
                }
            )
        summary.sort(key=lambda s: (-SEVERITY_WEIGHT.get(Severity(s["severity"]), 0), -s["count"]))
        return summary

    def to_dict(self) -> dict:
        """Return the stable machine-readable audit contract."""
        return {
            "score": self.score,
            "grade": self.grade,
            "sections_audited": self.sections_audited,
            "endpoints_audited": self.endpoints_audited,
            "critical": self.critical_count,
            "warnings": self.warning_count,
            "info": self.info_count,
            "summary": self.summary_by_rule(),
            "findings": [finding.to_dict() for finding in self.findings],
        }


# =========================================================================
# AUDIT CHECKS
# =========================================================================


def _check_missing_pagination(
    section: SectionInfo, endpoint: EndpointInfo, findings: list[AuditFinding]
):
    """List endpoints (GET, non-detail) without pagination."""
    # Only LIST-intent endpoints need pagination
    if endpoint.intent != EndpointIntent.LIST:
        return
    if "GET" not in endpoint.methods:
        return
    if endpoint.pagination_class:
        return

    display = endpoint.display_path or endpoint.path

    findings.append(
        AuditFinding(
            rule_id="MISSING_PAGINATION",
            severity=Severity.WARNING,
            title="Missing Pagination",
            description=(
                f"GET list endpoint '{display}' has no pagination class. "
                f"Large datasets will be returned in a single response, causing "
                f"performance degradation and potential timeouts."
            ),
            recommendation=(
                "Add a pagination_class to the ViewSet or view. Example: "
                "pagination_class = PageNumberPagination or set DEFAULT_PAGINATION_CLASS "
                "in REST_FRAMEWORK settings."
            ),
            endpoint_path=endpoint.path,
            section_name=section.name,
            section_slug=section.slug,
            endpoint_slug=endpoint.slug,
        )
    )


def _check_missing_authentication(
    section: SectionInfo, endpoint: EndpointInfo, findings: list[AuditFinding]
):
    """Endpoints with AllowAny that accept write operations."""
    has_write = any(m in endpoint.methods for m in ("POST", "PUT", "PATCH", "DELETE"))
    effective_write_permissions = endpoint.write_permissions or endpoint.permissions
    has_allow_any = "AllowAny" in effective_write_permissions

    if has_write and has_allow_any:
        # Intentional public ingestion endpoints must declare the concrete
        # controls that replace user authentication. Their domain tests are
        # responsible for proving those controls remain effective.
        if endpoint.public_write_controls:
            return

        # Skip known public-write intents (actions that are designed to be public)
        if endpoint.intent == EndpointIntent.ACTION:
            display = endpoint.display_path or endpoint.path
            last_seg = display.rstrip("/").split("/")[-1].lower().strip("{}").replace(":", "")
            public_actions = {
                "login", "register", "signup", "password_reset", "password-reset",
                "password-reset-confirm", "verify", "logout", "mfa", "send-code",
                "validate-business", "validate-phone", "validate-postal", "geocode",
            }
            if last_seg in public_actions:
                return

        path_lower = endpoint.path.lower()
        if any(
            segment in path_lower
            for segment in (
                "password-reset-confirm",
                "validate_phone",
                "validate_postal",
                "validate-business",
                "geocode/geocode",
                "/geocode/",
            )
        ):
            return

        display = endpoint.display_path or endpoint.path
        findings.append(
            AuditFinding(
                rule_id="UNPROTECTED_WRITE",
                severity=Severity.CRITICAL,
                title="Unprotected Write Endpoint",
                description=(
                    f"Endpoint '{display}' allows {', '.join(m for m in endpoint.methods if m in ('POST', 'PUT', 'PATCH', 'DELETE'))} "
                    f"with AllowAny permission. Any unauthenticated user can modify data."
                ),
                recommendation=(
                    "Replace AllowAny with IsAuthenticated or a more specific permission "
                    "class. If this endpoint must be public (e.g., registration), consider "
                    "adding throttling to prevent abuse."
                ),
                endpoint_path=endpoint.path,
                section_name=section.name,
                section_slug=section.slug,
                endpoint_slug=endpoint.slug,
            )
        )


def _check_missing_docstring(
    section: SectionInfo, endpoint: EndpointInfo, findings: list[AuditFinding]
):
    """Endpoints with no docstring documentation."""
    if endpoint.docstring:
        return
    # Root endpoints don't need docs
    if endpoint.intent == EndpointIntent.ROOT:
        return

    display = endpoint.display_path or endpoint.path
    findings.append(
        AuditFinding(
            rule_id="MISSING_DOCSTRING",
            severity=Severity.INFO,
            title="Missing Documentation",
            description=(
                f"Endpoint '{display}' ({endpoint.view_class}) has no docstring. "
                f"Other developers (and auto-generated docs) won't know what it does."
            ),
            recommendation=(
                "Add a docstring to the ViewSet or view class describing its purpose, "
                "expected inputs, and response format."
            ),
            endpoint_path=endpoint.path,
            section_name=section.name,
            section_slug=section.slug,
            endpoint_slug=endpoint.slug,
        )
    )


def _check_missing_filter_backends(
    section: SectionInfo, endpoint: EndpointInfo, findings: list[AuditFinding]
):
    """List endpoints without any filter backends."""
    # Only LIST-intent endpoints benefit from filter backends
    if endpoint.intent != EndpointIntent.LIST:
        return
    if "GET" not in endpoint.methods:
        return
    if endpoint.filter_backends:
        return

    display = endpoint.display_path or endpoint.path
    findings.append(
        AuditFinding(
            rule_id="MISSING_FILTERS",
            severity=Severity.INFO,
            title="No Filter Backends",
            description=(
                f"GET list endpoint '{display}' has no filter backends. "
                f"Clients cannot filter, search, or order results."
            ),
            recommendation=(
                "Add filter_backends = [IfinstaFilterBackend, SearchFilter, OrderingFilter] "
                "and define filterset_fields, search_fields, ordering_fields."
            ),
            endpoint_path=endpoint.path,
            section_name=section.name,
            section_slug=section.slug,
            endpoint_slug=endpoint.slug,
        )
    )


def _check_unbounded_list(
    section: SectionInfo, endpoint: EndpointInfo, findings: list[AuditFinding]
):
    """GET list endpoints with neither pagination nor filtering — worst case."""
    # Only LIST-intent endpoints can be unbounded
    if endpoint.intent != EndpointIntent.LIST:
        return
    if "GET" not in endpoint.methods:
        return
    if endpoint.pagination_class or endpoint.filter_backends:
        return

    display = endpoint.display_path or endpoint.path

    findings.append(
        AuditFinding(
            rule_id="UNBOUNDED_LIST",
            severity=Severity.CRITICAL,
            title="Unbounded List Response",
            description=(
                f"GET endpoint '{display}' has NO pagination AND NO filters. "
                f"As data grows, this endpoint will return increasingly large payloads, "
                f"potentially crashing clients or causing server memory exhaustion."
            ),
            recommendation=(
                "At minimum, add pagination (PageNumberPagination). Ideally, also add "
                "IfinstaFilterBackend and SearchFilter for client-side control."
            ),
            endpoint_path=endpoint.path,
            section_name=section.name,
            section_slug=section.slug,
            endpoint_slug=endpoint.slug,
        )
    )


def _check_missing_throttle(
    section: SectionInfo, endpoint: EndpointInfo, findings: list[AuditFinding]
):
    """Endpoints without rate limiting."""
    if endpoint.throttle_classes:
        return
    # Root and internal endpoints are less critical
    if endpoint.intent == EndpointIntent.ROOT:
        return

    display = endpoint.display_path or endpoint.path
    findings.append(
        AuditFinding(
            rule_id="MISSING_THROTTLE",
            severity=Severity.WARNING,
            title="No Rate Limiting",
            description=(
                f"Endpoint '{display}' has no throttle classes. "
                f"Without rate limiting, this endpoint is vulnerable to abuse "
                f"and denial-of-service attacks."
            ),
            recommendation=(
                "Add throttle_classes = [UserRateThrottle] or set "
                "DEFAULT_THROTTLE_CLASSES and DEFAULT_THROTTLE_RATES in "
                "REST_FRAMEWORK settings."
            ),
            endpoint_path=endpoint.path,
            section_name=section.name,
            section_slug=section.slug,
            endpoint_slug=endpoint.slug,
        )
    )


def _check_missing_serializer_on_write(
    section: SectionInfo, endpoint: EndpointInfo, findings: list[AuditFinding]
):
    """Write endpoints without a serializer — no input validation."""
    write_methods = [
        method
        for method in endpoint.methods
        if method in ("POST", "PUT", "PATCH")
    ]
    if not write_methods:
        return
    # Actions that don't need serializers (e.g., /mark-read/)
    if endpoint.intent == EndpointIntent.ACTION:
        return
    if endpoint.intent == EndpointIntent.ROOT:
        return

    if endpoint.request_serializers:
        missing_methods = [
            method
            for method in write_methods
            if not endpoint.request_serializers.get(method)
            or not endpoint.request_serializers[method].name
        ]
    else:
        request_serializer_name = (
            endpoint.request_serializer_name
            or endpoint.serializer_name
        )
        missing_methods = [] if request_serializer_name else write_methods

    if not missing_methods:
        return

    display = endpoint.display_path or endpoint.path
    findings.append(
        AuditFinding(
            rule_id="MISSING_SERIALIZER",
            severity=Severity.WARNING,
            title="Write Endpoint Without Serializer",
            description=(
                f"Endpoint '{display}' accepts {', '.join(missing_methods)} "
                f"but has no serializer. Input data is likely unvalidated."
            ),
            recommendation=(
                "Define a serializer_class for this view to ensure input validation, "
                "type coercion, and proper error messages."
            ),
            endpoint_path=endpoint.path,
            section_name=section.name,
            section_slug=section.slug,
            endpoint_slug=endpoint.slug,
            affected_methods=missing_methods,
        )
    )


def _check_field_validation(
    section: SectionInfo, endpoint: EndpointInfo, findings: list[AuditFinding]
):
    """Serializer fields missing validation constraints."""
    write_methods = {
        method
        for method in endpoint.methods
        if method in ("POST", "PUT", "PATCH")
    }
    if not write_methods:
        return

    if endpoint.request_serializers:
        schemas = {
            method: serializer
            for method, serializer in endpoint.request_serializers.items()
            if method in write_methods
        }
    else:
        fields = endpoint.request_serializer_fields or endpoint.serializer_fields
        name = endpoint.request_serializer_name or endpoint.serializer_name
        schemas = {
            method: SerializerInfo(name=name, fields=fields)
            for method in write_methods
            if fields
        }

    grouped: dict[tuple[str, tuple[str, ...]], list[str]] = {}
    for method, serializer in schemas.items():
        unbounded_fields = tuple(
            field_info.name
            for field_info in serializer.fields
            if not field_info.read_only
            and field_info.field_type in ("CharField", "TextField")
            and not field_info.max_length
        )
        if unbounded_fields:
            grouped.setdefault(
                (serializer.name, unbounded_fields),
                [],
            ).append(method)

    for (serializer_name, field_names), methods in grouped.items():
        findings.append(
            AuditFinding(
                rule_id="MISSING_MAX_LENGTH",
                severity=Severity.WARNING,
                title="Character Fields Without max_length",
                description=(
                    f"Endpoint '{endpoint.display_path or endpoint.path}' has {len(field_names)} "
                    f"character field(s) without max_length for {', '.join(methods)}: "
                    f"{', '.join(field_names)}. "
                    f"This allows arbitrarily long input that could bloat the database."
                ),
                recommendation=(
                    "Add max_length to all CharField and TextField definitions in the "
                    "serializer or model."
                ),
                endpoint_path=endpoint.path,
                section_name=section.name,
                section_slug=section.slug,
                endpoint_slug=endpoint.slug,
                affected_methods=methods,
                serializer_name=serializer_name,
            )
        )


def _check_large_serializer(
    section: SectionInfo, endpoint: EndpointInfo, findings: list[AuditFinding]
):
    """Serializers with many fields (response bloat risk)."""
    if endpoint.response_serializers:
        schemas = endpoint.response_serializers
    else:
        fields = endpoint.response_serializer_fields or endpoint.serializer_fields
        name = endpoint.response_serializer_name or endpoint.serializer_name
        methods = [
            method
            for method in endpoint.methods
            if method not in {"DELETE", "HEAD", "OPTIONS"}
        ]
        schemas = {
            method: SerializerInfo(name=name, fields=fields)
            for method in methods
            if fields
        }

    grouped: dict[tuple[str, int], list[str]] = {}
    for method, serializer in schemas.items():
        field_count = len(serializer.fields)
        if field_count >= 40:
            grouped.setdefault(
                (serializer.name, field_count),
                [],
            ).append(method)

    for (serializer_name, field_count), methods in grouped.items():
        findings.append(
            AuditFinding(
                rule_id="LARGE_SERIALIZER",
                severity=Severity.INFO,
                title="Large Serializer",
                description=(
                    f"Endpoint '{endpoint.display_path or endpoint.path}' exposes {field_count} "
                    f"fields for {', '.join(methods)}. "
                    f"Large serializers increase payload size and may expose data "
                    f"that clients don't need."
                ),
                recommendation=(
                    "Define explicit, purpose-specific list and detail response "
                    "serializers with stable field allowlists. Only offer dynamic "
                    "field selection when the API implements and tests that contract."
                ),
                endpoint_path=endpoint.path,
                section_name=section.name,
                section_slug=section.slug,
                endpoint_slug=endpoint.slug,
                affected_methods=methods,
                serializer_name=serializer_name,
            )
        )


def _check_weak_permissions(
    section: SectionInfo, endpoint: EndpointInfo, findings: list[AuditFinding]
):
    """Write endpoints with only IsAuthenticated (no object-level perms)."""
    has_write = any(m in endpoint.methods for m in ("PUT", "PATCH", "DELETE"))
    if not has_write:
        return

    # Only IsAuthenticated, no finer-grained permissions
    effective_write_permissions = endpoint.write_permissions or endpoint.permissions
    if effective_write_permissions == ["IsAuthenticated"]:
        findings.append(
            AuditFinding(
                rule_id="WEAK_PERMISSIONS",
                severity=Severity.WARNING,
                title="Only IsAuthenticated on Mutating Endpoint",
                description=(
                    f"Endpoint '{endpoint.display_path or endpoint.path}' allows {', '.join(m for m in endpoint.methods if m in ('PUT', 'PATCH', 'DELETE'))} "
                    f"with only IsAuthenticated. Any logged-in user can modify/delete this resource."
                ),
                recommendation=(
                    "Add object-level permissions (e.g., IsOwner, IsAdminUser) to ensure "
                    "users can only modify resources they own."
                ),
                endpoint_path=endpoint.path,
                section_name=section.name,
                section_slug=section.slug,
                endpoint_slug=endpoint.slug,
            )
        )


def _check_inconsistent_naming(
    section: SectionInfo, endpoint: EndpointInfo, findings: list[AuditFinding]
):
    """URL patterns that don't follow REST conventions."""
    path = endpoint.path.lower()

    # Phase 1.3: Single combined regex match instead of 7 separate re.search calls
    if _VERB_PATTERN.search(path):
        findings.append(
            AuditFinding(
                rule_id="VERB_IN_URL",
                severity=Severity.INFO,
                title="Verb-Based URL Pattern",
                description=(
                    f"Endpoint '{endpoint.display_path or endpoint.path}' contains a verb in the URL path. "
                    f"RESTful APIs should use HTTP methods (GET, POST, PUT, DELETE) "
                    f"instead of verbs in URLs."
                ),
                recommendation=(
                    "Use resource-based URLs (e.g., /api/v1/users/) and let the HTTP "
                    "method convey the action."
                ),
                endpoint_path=endpoint.path,
                section_name=section.name,
                section_slug=section.slug,
                endpoint_slug=endpoint.slug,
            )
        )


# =========================================================================
# AUDIT RUNNER
# =========================================================================

# All audit checks
AUDIT_CHECKS = [
    _check_unbounded_list,
    _check_missing_pagination,
    _check_missing_authentication,
    _check_missing_docstring,
    _check_missing_filter_backends,
    _check_missing_throttle,
    _check_missing_serializer_on_write,
    _check_field_validation,
    _check_weak_permissions,
    _check_large_serializer,
    _check_inconsistent_naming,
]


def _finding_logical_key(
    finding: AuditFinding,
    endpoint: EndpointInfo,
) -> str:
    """Build a route-alias-stable identity for one audit concern."""
    serializer_identity = (
        finding.serializer_name
        or endpoint.response_serializer_name
        or endpoint.request_serializer_name
        or endpoint.serializer_name
    )
    return "|".join(
        (
            finding.rule_id,
            endpoint.view_class,
            endpoint.action_name,
            serializer_identity,
        )
    )


def _group_logically_identical_findings(
    findings: list[AuditFinding],
) -> list[AuditFinding]:
    """Collapse route aliases while preserving every affected endpoint path."""
    grouped: dict[str, AuditFinding] = {}
    ungrouped_index = 0

    for finding in findings:
        if not finding.affected_endpoint_paths and finding.endpoint_path:
            finding.affected_endpoint_paths = [finding.endpoint_path]

        key = finding.logical_key
        if not key:
            key = f"ungrouped:{ungrouped_index}"
            ungrouped_index += 1

        existing = grouped.get(key)
        if existing is None:
            grouped[key] = finding
            continue

        for path in finding.affected_endpoint_paths:
            if path not in existing.affected_endpoint_paths:
                existing.affected_endpoint_paths.append(path)
        for method in finding.affected_methods:
            if method not in existing.affected_methods:
                existing.affected_methods.append(method)

    return list(grouped.values())


def run_audit(sections: list[SectionInfo] | None = None) -> AuditReport:
    """
    Run all audit checks across all API sections.

    Returns an AuditReport with findings, scores, and summary.
    """
    if sections is None:
        sections = discover_api_endpoints()

    report = AuditReport()
    report.sections_audited = len(sections)

    total_endpoints = 0
    seen_paths = set()

    for section in sections:
        for endpoint in section.endpoints:
            # Avoid duplicate checks for same path
            if endpoint.path in seen_paths:
                continue
            seen_paths.add(endpoint.path)
            total_endpoints += 1

            for check_fn in AUDIT_CHECKS:
                previous_count = len(report.findings)
                check_fn(section, endpoint, report.findings)
                for finding in report.findings[previous_count:]:
                    finding.logical_key = _finding_logical_key(
                        finding,
                        endpoint,
                    )
                    finding.affected_endpoint_paths = [endpoint.path]

    report.endpoints_audited = total_endpoints
    report.findings = _group_logically_identical_findings(report.findings)

    # Sort findings: CRITICAL first, then WARNING, then INFO
    report.findings.sort(key=lambda f: (-SEVERITY_WEIGHT[f.severity], f.endpoint_path))

    return report


def get_endpoint_findings(endpoint_path: str) -> list[AuditFinding]:
    """Get audit findings for a specific endpoint (for inline display)."""
    report = run_audit()
    return report.findings_for_endpoint(endpoint_path)


# =========================================================================
# REPORT FILE GENERATOR
# =========================================================================

def generate_report(
    output_path: str | None = None,
    report: AuditReport | None = None,
) -> str:
    """
    Generate a Markdown audit report file with active errors and warnings.

    Only CRITICAL and WARNING findings are included (actionable items).
    INFO-level findings are summarized but not listed individually.

    Args:
        output_path: Full path for the report file. If None, writes to
                     the project root as MYDOC_AUDIT_REPORT.md.

    Returns:
        The absolute path to the generated file.
    """
    from django.conf import settings

    from .config import get_setting

    report = report or run_audit()

    if output_path is None:
        default_path = get_setting("REPORT_OUTPUT_PATH", os.path.join(settings.BASE_DIR, "MYDOC_AUDIT_REPORT.md"))
        output_path = default_path

    # Separate findings by severity
    critical_findings = [f for f in report.findings if f.severity == Severity.CRITICAL]
    warning_findings = [f for f in report.findings if f.severity == Severity.WARNING]
    info_findings = [f for f in report.findings if f.severity == Severity.INFO]

    # Group critical + warning by section
    section_groups: dict[str, list[AuditFinding]] = {}
    for f in critical_findings + warning_findings:
        key = f.section_name or "General"
        section_groups.setdefault(key, []).append(f)

    # Build the markdown
    lines: list[str] = []

    # ── Header ──
    lines.append("# MyDoc API Audit Report")
    lines.append("")
    lines.append(f"> **Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"> **Health Grade:** {report.grade} ({report.score}/100)")
    lines.append(f"> **Endpoints Audited:** {report.endpoints_audited}")
    lines.append(f"> **Sections Audited:** {report.sections_audited}")
    lines.append("")

    # ── Quick Summary ──
    lines.append("## Summary")
    lines.append("")
    lines.append("| Severity | Count | Status |")
    lines.append("|----------|-------|--------|")
    lines.append(
        f"| CRITICAL | {report.critical_count} | "
        f"{'Needs immediate attention' if report.critical_count > 0 else 'All clear'} |"
    )
    lines.append(
        f"| WARNING  | {report.warning_count} | "
        f"{'Should be addressed' if report.warning_count > 0 else 'All clear'} |"
    )
    lines.append(
        f"| INFO     | {report.info_count} | "
        f"{'Recommendations available' if report.info_count > 0 else 'All clear'} |"
    )
    lines.append("")

    # ── Issues by Category ──
    summary = report.summary_by_rule()
    # Only show critical + warning rules
    actionable_rules = [r for r in summary if r["severity"] in ("critical", "warning")]

    if actionable_rules:
        lines.append("## Issues by Category")
        lines.append("")
        lines.append("| Rule | Severity | Affected Endpoints | Recommendation |")
        lines.append("|------|----------|--------------------|----------------|")
        for rule in actionable_rules:
            lines.append(
                f"| {rule['title']} | {rule['severity'].upper()} | "
                f"{rule['count']} | {rule['recommendation'][:80]}... |"
            )
        lines.append("")

    # ── No issues? ──
    if not critical_findings and not warning_findings:
        lines.append("## Status: All Clear")
        lines.append("")
        lines.append("No critical or warning-level issues found. Your API is in good shape.")
        lines.append("")
        if info_findings:
            lines.append(
                f"There are {len(info_findings)} informational suggestions available. "
                f"Visit the [Audit Dashboard](/mydoc/audit/) for details."
            )
            lines.append("")
    else:
        # ── Critical Findings ──
        if critical_findings:
            lines.append("---")
            lines.append("")
            lines.append(f"## CRITICAL Issues ({len(critical_findings)})")
            lines.append("")
            lines.append(
                "These issues pose immediate risks and should be fixed as soon as possible."
            )
            lines.append("")

            for f in critical_findings:
                lines.append(f"### [{f.rule_id}] {f.endpoint_path}")
                lines.append("")
                lines.append(f"**{f.title}** | Section: {f.section_name}")
                lines.append("")
                lines.append(f"  {f.description}")
                lines.append("")
                if f.affected_endpoint_count > 1:
                    lines.append(
                        "  **Affected routes:** "
                        + ", ".join(
                            f"`{path}`" for path in f.affected_endpoint_paths
                        )
                    )
                    lines.append("")
                lines.append(f"  **Fix:** {f.recommendation}")
                lines.append("")

        # ── Warning Findings by Section ──
        if warning_findings:
            lines.append("---")
            lines.append("")
            lines.append(f"## WARNING Issues ({len(warning_findings)})")
            lines.append("")
            lines.append("These issues should be addressed to improve API quality and security.")
            lines.append("")

            # Group warnings by section for readability
            warning_by_section: dict[str, list[AuditFinding]] = {}
            for f in warning_findings:
                key = f.section_name or "General"
                warning_by_section.setdefault(key, []).append(f)

            for section_name, findings in sorted(warning_by_section.items()):
                lines.append(f"### {section_name} ({len(findings)} warnings)")
                lines.append("")
                lines.append("| Endpoint | Issue | Fix |")
                lines.append("|----------|-------|-----|")
                for f in findings:
                    # Truncate long descriptions for the table
                    short_desc = f.title
                    short_fix = f.recommendation[:100]
                    endpoint_paths = "<br>".join(
                        f"`{path}`"
                        for path in (
                            f.affected_endpoint_paths
                            or [f.endpoint_path]
                        )
                    )
                    lines.append(f"| {endpoint_paths} | {short_desc} | {short_fix} |")
                lines.append("")

    # ── Info Summary (counts only) ──
    if info_findings:
        lines.append("---")
        lines.append("")
        lines.append(f"## Informational ({len(info_findings)} items)")
        lines.append("")
        lines.append("These are suggestions for improvement, not blocking issues.")
        lines.append("")

        info_by_rule: dict[str, int] = {}
        for f in info_findings:
            info_by_rule[f.title] = (
                info_by_rule.get(f.title, 0)
                + f.affected_endpoint_count
            )

        lines.append("| Category | Count |")
        lines.append("|----------|-------|")
        for title, count in sorted(info_by_rule.items(), key=lambda x: -x[1]):
            lines.append(f"| {title} | {count} |")
        lines.append("")

    # ── Footer ──
    lines.append("---")
    lines.append("")
    lines.append("*This report was auto-generated by [MyDoc API Auditor](/mydoc/audit/).*")
    lines.append("*Re-run the audit to refresh: `python manage.py mydoc_audit`*")
    lines.append("")

    # Write file
    content = "\n".join(lines)
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(content)

    return output_path


def generate_json_report(
    output_path: str | None = None,
    report: AuditReport | None = None,
) -> str:
    """Write a deterministic machine-readable audit report."""
    from django.conf import settings

    report = report or run_audit()
    output_path = output_path or os.path.join(settings.BASE_DIR, "audit-report.json")
    content = json.dumps(
        report.to_dict(),
        indent=2,
        sort_keys=True,
    )
    with open(output_path, "w", encoding="utf-8", newline="\n") as report_file:
        report_file.write(f"{content}\n")
    return output_path
