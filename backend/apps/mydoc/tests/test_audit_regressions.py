from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.test import RequestFactory, TestCase
from django.test.utils import override_settings
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from backend.apps.core.accounts.api import urlpatterns as accounts_urlpatterns
from backend.apps.core.base.api_schema import api_schema
from backend.apps.core.mydoc.auditor import (
    AuditFinding,
    AuditReport,
    Severity,
    _check_field_validation,
    _check_large_serializer,
    _check_missing_authentication,
    _check_missing_serializer_on_write,
    run_audit,
)
from backend.apps.core.mydoc.introspection import (
    SECTIONS_CACHE_KEY,
    EndpointInfo,
    EndpointIntent,
    FieldInfo,
    SectionInfo,
    SerializerInfo,
    _get_endpoint_serializer_info,
    _get_permissions,
    _invalidate_cache,
    discover_api_endpoints,
)
from backend.apps.core.mydoc.views import MyDocAuditView


class _LargeAuditSerializer(serializers.Serializer):
    field_01 = serializers.CharField()
    field_02 = serializers.CharField()
    field_03 = serializers.CharField()
    field_04 = serializers.CharField()
    field_05 = serializers.CharField()
    field_06 = serializers.CharField()
    field_07 = serializers.CharField()
    field_08 = serializers.CharField()
    field_09 = serializers.CharField()
    field_10 = serializers.CharField()
    field_11 = serializers.CharField()
    field_12 = serializers.CharField()
    field_13 = serializers.CharField()
    field_14 = serializers.CharField()
    field_15 = serializers.CharField()
    field_16 = serializers.CharField()
    field_17 = serializers.CharField()
    field_18 = serializers.CharField()
    field_19 = serializers.CharField()
    field_20 = serializers.CharField()
    field_21 = serializers.CharField()
    field_22 = serializers.CharField()
    field_23 = serializers.CharField()
    field_24 = serializers.CharField()
    field_25 = serializers.CharField()
    field_26 = serializers.CharField()
    field_27 = serializers.CharField()
    field_28 = serializers.CharField()
    field_29 = serializers.CharField()
    field_30 = serializers.CharField()
    field_31 = serializers.CharField()
    field_32 = serializers.CharField()
    field_33 = serializers.CharField()
    field_34 = serializers.CharField()
    field_35 = serializers.CharField()
    field_36 = serializers.CharField()
    field_37 = serializers.CharField()
    field_38 = serializers.CharField()
    field_39 = serializers.CharField()
    field_40 = serializers.CharField()


class _SummaryAuditSerializer(serializers.Serializer):
    total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)


class _ActionAwareAuditViewSet(viewsets.ViewSet):
    serializer_class = _LargeAuditSerializer

    @api_schema(response_serializer=_SummaryAuditSerializer)
    @action(detail=False, methods=["get"])
    def summary(self, _request):
        return Response({"total": "0.00"})


class _DecoratorSerializerAuditViewSet(viewsets.ViewSet):
    serializer_class = _LargeAuditSerializer

    @action(
        detail=False,
        methods=["get"],
        serializer_class=_SummaryAuditSerializer,
    )
    def summary(self, _request):
        return Response({"total": "0.00"})


class MyDocAuditRegressionTests(TestCase):
    def test_ci_workflow_enforces_and_uploads_api_audit(self) -> None:
        workflow_path = (
            Path(settings.BASE_DIR)
            / ".github"
            / "workflows"
            / "api-contract-audit.yml"
        )

        source = workflow_path.read_text(encoding="utf-8")

        self.assertIn(
            "python manage.py mydoc_audit --format json "
            "--output audit-report.json --fail-on info",
            source,
        )
        self.assertIn("uses: actions/upload-artifact@v4", source)
        self.assertIn("if: always()", source)
        self.assertIn("DJANGO_SETTINGS_MODULE: backend.config.settings.testing", source)

    def test_large_serializer_check_inspects_every_response_method(self) -> None:
        small_fields = [
            FieldInfo(name=f"small_{index}", field_type="CharField")
            for index in range(2)
        ]
        large_fields = [
            FieldInfo(name=f"large_{index}", field_type="CharField")
            for index in range(40)
        ]
        section = SectionInfo(name="Example", slug="example")
        endpoint = EndpointInfo(
            path="/api/example/resources/",
            methods=["GET", "POST"],
            response_serializer_name="SmallSerializer",
            response_serializer_fields=small_fields,
            response_serializers={
                "GET": SerializerInfo(name="SmallSerializer", fields=small_fields),
                "POST": SerializerInfo(name="LargeSerializer", fields=large_fields),
            },
        )

        findings: list[AuditFinding] = []
        _check_large_serializer(section, endpoint, findings)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].serializer_name, "LargeSerializer")
        self.assertEqual(findings[0].affected_methods, ["POST"])

    def test_field_validation_check_inspects_every_request_method(self) -> None:
        bounded = FieldInfo(
            name="name",
            field_type="CharField",
            max_length=100,
        )
        unbounded = FieldInfo(name="notes", field_type="CharField")
        section = SectionInfo(name="Example", slug="example")
        endpoint = EndpointInfo(
            path="/api/example/resources/{pk}/",
            methods=["PATCH", "POST"],
            request_serializers={
                "POST": SerializerInfo(name="CreateSerializer", fields=[bounded]),
                "PATCH": SerializerInfo(name="UpdateSerializer", fields=[unbounded]),
            },
        )

        findings: list[AuditFinding] = []
        _check_field_validation(section, endpoint, findings)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].serializer_name, "UpdateSerializer")
        self.assertEqual(findings[0].affected_methods, ["PATCH"])

    def test_missing_serializer_check_inspects_every_write_method(self) -> None:
        section = SectionInfo(name="Example", slug="example")
        endpoint = EndpointInfo(
            path="/api/example/resources/{pk}/",
            methods=["PATCH", "POST"],
            request_serializers={
                "POST": SerializerInfo(name="CreateSerializer", fields=[]),
            },
        )

        findings: list[AuditFinding] = []
        _check_missing_serializer_on_write(section, endpoint, findings)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].affected_methods, ["PATCH"])

    def test_action_response_schema_overrides_viewset_serializer(self) -> None:
        callback = _ActionAwareAuditViewSet.as_view({"get": "summary"})

        request_serializers, response_serializers = _get_endpoint_serializer_info(
            callback,
            _ActionAwareAuditViewSet,
        )

        self.assertNotIn("GET", request_serializers)
        self.assertEqual(response_serializers["GET"].name, "_SummaryAuditSerializer")
        self.assertEqual(
            [field.name for field in response_serializers["GET"].fields],
            ["total"],
        )

    def test_action_serializer_class_kwarg_is_resolved_per_route(self) -> None:
        callback = _DecoratorSerializerAuditViewSet.as_view({"get": "summary"})

        _request_serializers, response_serializers = _get_endpoint_serializer_info(
            callback,
            _DecoratorSerializerAuditViewSet,
        )

        self.assertEqual(response_serializers["GET"].name, "_SummaryAuditSerializer")

    def test_logically_identical_findings_retain_every_route(self) -> None:
        fields = [
            FieldInfo(name=f"field_{index}", field_type="CharField", read_only=True)
            for index in range(40)
        ]
        section = SectionInfo(
            name="Discover",
            slug="discover",
            endpoints=[
                EndpointInfo(
                    path="/api/discover/storefronts/",
                    methods=["GET"],
                    view_class="MerchantStorefrontViewSet",
                    action_name="list",
                    response_serializer_name="MerchantStorefrontSerializer",
                    response_serializer_fields=fields,
                ),
                EndpointInfo(
                    path="/api/v1/discover/storefronts/",
                    methods=["GET"],
                    view_class="MerchantStorefrontViewSet",
                    action_name="list",
                    response_serializer_name="MerchantStorefrontSerializer",
                    response_serializer_fields=fields,
                ),
            ],
        )

        report = run_audit([section])

        large_findings = [
            finding for finding in report.findings
            if finding.rule_id == "LARGE_SERIALIZER"
        ]
        self.assertEqual(len(large_findings), 1)
        self.assertEqual(
            large_findings[0].affected_endpoint_paths,
            [
                "/api/discover/storefronts/",
                "/api/v1/discover/storefronts/",
            ],
        )

    @patch("backend.apps.core.mydoc.views.get_endpoint_by_slug")
    def test_endpoint_view_redirects_stale_base_bootstrap_slug(self, mock_get_endpoint_by_slug) -> None:
        endpoint = EndpointInfo(
            path="/api/v1/bootstrap/",
            display_path="/api/v1/bootstrap/",
            methods=["GET"],
        )

        def lookup(section_slug: str, endpoint_slug: str):
            if section_slug == "base" and endpoint_slug == "api-v1-bootstrap":
                return endpoint
            return None

        mock_get_endpoint_by_slug.side_effect = lookup

        response = self.client.get("/mydoc/base/api-v1-base-bootstrap/")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/mydoc/base/api-v1-bootstrap/")

    @patch("backend.apps.core.mydoc.views.discover_api_endpoints", return_value=[])
    @patch("backend.apps.core.mydoc.views.get_section_by_slug", return_value=None)
    @patch("backend.apps.core.mydoc.views.get_endpoint_by_slug", return_value=None)
    def test_endpoint_view_renders_missing_endpoint_without_template_error(
        self,
        _mock_get_endpoint_by_slug,
        _mock_get_section_by_slug,
        _mock_discover_api_endpoints,
    ) -> None:
        response = self.client.get("/mydoc/base/not-found/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Endpoint Not Found")

    def test_route_specific_permissions_are_used_for_mfa_manage(self) -> None:
        callback = next(
            pattern.callback
            for pattern in accounts_urlpatterns
            if getattr(pattern, "name", "") == "mfa_manage"
        )

        permissions, write_permissions = _get_permissions(callback, callback.cls)

        self.assertEqual(permissions, ["IsAuthenticated"])
        self.assertEqual(write_permissions, ["IsAuthenticated"])

    def test_audit_ignores_public_password_reset_confirm_endpoint(self) -> None:
        section = SectionInfo(name="Accounts", slug="accounts")
        endpoint = EndpointInfo(
            path="/api/v1/accounts/password-reset-confirm/<uidb64>/<token>/",
            display_path="/api/v1/accounts/password-reset-confirm/{uidb64}/{token}/",
            methods=["POST"],
            permissions=["AllowAny"],
            write_permissions=["AllowAny"],
            intent=EndpointIntent.ACTION,
        )

        findings = []
        _check_missing_authentication(section, endpoint, findings)

        self.assertEqual(findings, [])

    def test_audit_accepts_reviewed_controls_on_public_write_endpoints(self) -> None:
        section = SectionInfo(name="Payments", slug="payments")
        endpoint = EndpointInfo(
            path="/api/v1/pay/webhooks/<str:provider>/",
            methods=["POST"],
            permissions=["AllowAny"],
            write_permissions=["AllowAny"],
            public_write_controls=[
                "provider_signature",
                "replay_deduplication",
                "anonymous_throttle",
            ],
        )

        findings = []
        _check_missing_authentication(section, endpoint, findings)

        self.assertEqual(findings, [])

    def test_webhook_path_without_declared_controls_remains_a_finding(self) -> None:
        section = SectionInfo(name="Example", slug="example")
        endpoint = EndpointInfo(
            path="/api/v1/example/webhooks/",
            methods=["POST"],
            permissions=["AllowAny"],
            write_permissions=["AllowAny"],
        )

        findings = []
        _check_missing_authentication(section, endpoint, findings)

        self.assertEqual([finding.rule_id for finding in findings], ["UNPROTECTED_WRITE"])

    def test_critical_findings_cannot_receive_an_a_grade(self) -> None:
        report = AuditReport(
            findings=[
                AuditFinding(
                    rule_id="UNPROTECTED_WRITE",
                    severity=Severity.CRITICAL,
                    title="Unprotected Write Endpoint",
                    description="Critical test finding.",
                    recommendation="Protect it.",
                )
            ],
            endpoints_audited=1_478,
        )

        self.assertLess(report.score, 90)
        self.assertNotEqual(report.grade, "A")

    @patch("backend.apps.core.mydoc.management.commands.mydoc_audit.generate_report")
    @patch("backend.apps.core.mydoc.management.commands.mydoc_audit.run_audit")
    def test_management_command_stdout_flag_prints_findings(
        self, mock_run_audit, mock_generate_report
    ) -> None:
        mock_run_audit.return_value = AuditReport(
            findings=[],
            sections_audited=1,
            endpoints_audited=1,
        )

        call_command("mydoc_audit", "--stdout")

        mock_run_audit.assert_called_once()
        mock_generate_report.assert_not_called()

    def test_audit_report_json_is_deterministic_and_complete(self) -> None:
        report = AuditReport(
            findings=[
                AuditFinding(
                    rule_id="MISSING_MAX_LENGTH",
                    severity=Severity.WARNING,
                    title="Missing max length",
                    description="Example",
                    recommendation="Bound the field.",
                    endpoint_path="/api/example/",
                    affected_methods=["PATCH"],
                    serializer_name="ExampleSerializer",
                )
            ],
            sections_audited=2,
            endpoints_audited=3,
        )

        payload = report.to_dict()

        self.assertEqual(payload["warnings"], 1)
        self.assertEqual(payload["findings"][0]["affected_methods"], ["PATCH"])
        self.assertEqual(
            json.loads(json.dumps(payload, sort_keys=True)),
            payload,
        )

    @patch(
        "backend.apps.core.mydoc.management.commands.mydoc_audit.generate_json_report"
    )
    @patch("backend.apps.core.mydoc.management.commands.mydoc_audit.run_audit")
    def test_management_command_writes_json_from_the_audited_report(
        self,
        mock_run_audit,
        mock_generate_json_report,
    ) -> None:
        report = AuditReport(sections_audited=1, endpoints_audited=1)
        mock_run_audit.return_value = report

        with TemporaryDirectory() as directory:
            output_path = Path(directory) / "audit.json"
            mock_generate_json_report.return_value = str(output_path)
            call_command(
                "mydoc_audit",
                "--format",
                "json",
                "--output",
                str(output_path),
            )

        mock_generate_json_report.assert_called_once_with(
            output_path=str(output_path),
            report=report,
        )

    @patch("backend.apps.core.mydoc.management.commands.mydoc_audit.run_audit")
    def test_management_command_can_fail_on_warning(
        self,
        mock_run_audit,
    ) -> None:
        mock_run_audit.return_value = AuditReport(
            findings=[
                AuditFinding(
                    rule_id="EXAMPLE",
                    severity=Severity.WARNING,
                    title="Example warning",
                    description="Example",
                    recommendation="Fix it.",
                )
            ],
            sections_audited=1,
            endpoints_audited=1,
        )

        with self.assertRaises(CommandError):
            call_command(
                "mydoc_audit",
                "--stdout",
                "--fail-on",
                "warning",
                stdout=StringIO(),
            )

    @override_settings(MYDOC_CONFIG={"CACHE_ENABLED": True, "CACHE_TTL": 300})
    def test_discovery_uses_django_cache_after_local_cache_reset(self) -> None:
        cached_sections = [SectionInfo(name="Cached", slug="cached")]
        _invalidate_cache()
        cache.set(SECTIONS_CACHE_KEY, cached_sections, timeout=300)

        with patch("backend.apps.core.mydoc.introspection.get_resolver") as mock_resolver:
            sections = discover_api_endpoints()

        self.assertEqual(sections, cached_sections)
        mock_resolver.assert_not_called()
        _invalidate_cache()

    @patch("backend.apps.core.mydoc.views.run_audit")
    @patch("backend.apps.core.mydoc.views.discover_api_endpoints")
    def test_audit_view_reuses_sections_within_request(
        self, mock_discover_api_endpoints, mock_run_audit
    ) -> None:
        sections = [
            SectionInfo(name="Accounts", slug="accounts"),
            SectionInfo(name="Payments", slug="payments"),
        ]
        report = AuditReport(findings=[], sections_audited=1, endpoints_audited=1)
        mock_discover_api_endpoints.return_value = sections
        mock_run_audit.return_value = report

        request = RequestFactory().get("/mydoc/audit/")
        view = MyDocAuditView()
        view.setup(request)
        context = view.get_context_data()

        self.assertEqual(context["sections"], sections)
        self.assertIs(context["report"], report)
        self.assertEqual(
            [section["slug"] for section in context["audit_sidebar_sections"]],
            ["accounts", "payments"],
        )
        mock_discover_api_endpoints.assert_called_once()
        mock_run_audit.assert_called_once_with(sections)

    def test_current_api_has_no_actionable_audit_findings(self) -> None:
        _invalidate_cache()

        report = run_audit()
        actionable = [
            (finding.rule_id, finding.endpoint_path)
            for finding in report.findings
            if finding.severity in {Severity.CRITICAL, Severity.WARNING}
        ]

        self.assertEqual(actionable, [])

    def test_custom_actions_do_not_inherit_large_resource_findings(self) -> None:
        _invalidate_cache()

        report = run_audit()
        custom_action_names = {
            "clear_cache",
            "follow",
            "increment_view",
            "payment_methods",
            "pickup_locations",
            "summary",
            "unfollow",
        }

        false_positives = [
            finding.endpoint_path
            for finding in report.findings
            if finding.rule_id == "LARGE_SERIALIZER"
            and any(
                f"/{action_name.replace('_', '-')}/" in (
                    finding.endpoint_path.replace("_", "-")
                )
                for action_name in custom_action_names
            )
        ]

        self.assertEqual(false_positives, [])
