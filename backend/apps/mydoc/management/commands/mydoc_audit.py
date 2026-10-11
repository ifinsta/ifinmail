"""
MyDoc Audit Management Command

Runs the API auditor and generates a Markdown report file
(MYDOC_AUDIT_REPORT.md) in the project root.

Usage:
    python manage.py mydoc_audit
    python manage.py mydoc_audit --output /path/to/report.md
    python manage.py mydoc_audit --format json --output audit-report.json
    python manage.py mydoc_audit --format json --fail-on warning
    python manage.py mydoc_audit --severity critical
    python manage.py mydoc_audit --stdout
"""

from django.core.management.base import BaseCommand, CommandError

from backend.apps.core.mydoc.auditor import (
    Severity,
    generate_json_report,
    generate_report,
    run_audit,
)


class Command(BaseCommand):
    help = "Run the MyDoc API auditor and generate a Markdown report file."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            "-o",
            type=str,
            default=None,
            help="Output path for the report file (default: MYDOC_AUDIT_REPORT.md in project root).",
        )
        parser.add_argument(
            "--stdout",
            dest="print_findings",
            action="store_true",
            help="Print a summary to stdout instead of writing a file.",
        )
        parser.add_argument(
            "--severity",
            type=str,
            choices=["critical", "warning", "info"],
            default=None,
            help="Only show findings of a specific severity.",
        )
        parser.add_argument(
            "--format",
            choices=["markdown", "json"],
            default="markdown",
            help="Report format when writing a file (default: markdown).",
        )
        parser.add_argument(
            "--fail-on",
            choices=["critical", "warning", "info"],
            default=None,
            help="Exit non-zero when findings at or above this severity exist.",
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("Running MyDoc API Audit..."))
        self.stdout.write("")

        report = run_audit()

        # Print summary to console
        self.stdout.write(f"  Endpoints audited: {report.endpoints_audited}")
        self.stdout.write(f"  Sections audited:  {report.sections_audited}")
        self.stdout.write(f"  Health Grade:      {report.grade} ({report.score}/100)")
        self.stdout.write("")

        # Severity counts
        if report.critical_count > 0:
            self.stdout.write(self.style.ERROR(f"  CRITICAL:  {report.critical_count}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"  CRITICAL:  {report.critical_count}"))

        if report.warning_count > 0:
            self.stdout.write(self.style.WARNING(f"  WARNING:   {report.warning_count}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"  WARNING:   {report.warning_count}"))

        self.stdout.write(f"  INFO:      {report.info_count}")
        self.stdout.write("")

        # Optional: filter by severity and print to stdout
        if options.get("print_findings"):
            severity_filter = options.get("severity")
            findings = report.findings

            if severity_filter:
                sev = Severity(severity_filter)
                findings = [f for f in findings if f.severity == sev]

            if not findings:
                self.stdout.write(self.style.SUCCESS("  No findings to display."))
            else:
                for f in findings:
                    if f.severity == Severity.CRITICAL:
                        style = self.style.ERROR
                    elif f.severity == Severity.WARNING:
                        style = self.style.WARNING
                    else:
                        style = self.style.NOTICE

                    self.stdout.write(style(f"  [{f.severity_label}] {f.rule_id}"))
                    self.stdout.write(f"    Path:  {f.endpoint_path}")
                    if f.affected_methods:
                        self.stdout.write(
                            f"    Methods: {', '.join(f.affected_methods)}"
                        )
                    self.stdout.write(f"    Issue: {f.title}")
                    self.stdout.write(f"    Fix:   {f.recommendation}")
                    self.stdout.write("")
        else:
            report_format = options["format"]
            if report_format == "json":
                output_path = generate_json_report(
                    output_path=options.get("output"),
                    report=report,
                )
            else:
                output_path = generate_report(
                    output_path=options.get("output"),
                    report=report,
                )
            self.stdout.write(self.style.SUCCESS(f"  Report generated: {output_path}"))
            self.stdout.write("")

        # Quick actionable summary
        if report.critical_count > 0:
            self.stdout.write(
                self.style.ERROR(
                    f"  {report.critical_count} critical issue(s) require immediate attention!"
                )
            )
        if report.warning_count > 0:
            self.stdout.write(
                self.style.WARNING(f"  {report.warning_count} warning(s) should be addressed.")
            )
        if report.critical_count == 0 and report.warning_count == 0:
            self.stdout.write(self.style.SUCCESS("  All clear! No actionable issues found."))

        fail_on = options.get("fail_on")
        failing_severities = {
            "critical": {Severity.CRITICAL},
            "warning": {Severity.CRITICAL, Severity.WARNING},
            "info": {Severity.CRITICAL, Severity.WARNING, Severity.INFO},
        }
        if fail_on and any(
            finding.severity in failing_severities[fail_on]
            for finding in report.findings
        ):
            raise CommandError(
                f"MyDoc audit failed: findings at or above {fail_on} severity."
            )
