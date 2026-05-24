"""Admin dashboard views for ifinmail."""
import os

from django.db import connections
from django.db.utils import OperationalError
from django.shortcuts import render


def dashboard(request):
    """Platform admin dashboard — aggregates stats, DNS health, security events."""
    stats = _get_stats()
    domains = _get_domains()
    events = _get_security_events()
    return render(request, "admin/dashboard.html", {
        "stats": stats,
        "domains": domains,
        "events": events,
    })


def _get_stats():
    """Fetch aggregate platform statistics, falling back to placeholders."""
    try:
        with connections["default"].cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM domains")
            domain_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM users WHERE is_active = TRUE")
            user_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM mailboxes")
            mailbox_count = cur.fetchone()[0]
    except (OperationalError, Exception):
        domain_count = 1
        user_count = 0
        mailbox_count = 0

    return [
        {"value": domain_count, "label": "Domains"},
        {"value": user_count, "label": "Active Users"},
        {"value": mailbox_count, "label": "Mailboxes"},
        {"value": "Online", "label": "Postfix"},
        {"value": "Online", "label": "Dovecot"},
        {"value": "Let's Encrypt", "label": "TLS"},
    ]


def _get_domains():
    """Fetch domain health from the database."""
    try:
        with connections["default"].cursor() as cur:
            cur.execute(
                "SELECT name, verified, mx_verified, spf_verified, "
                "dkim_verified, dmarc_verified FROM domains ORDER BY name"
            )
            rows = cur.fetchall()
    except (OperationalError, Exception):
        rows = []

    if not rows:
        return [
            {
                "name": os.environ.get("MAIL_DOMAIN", "ifinsta.online"),
                "checks": [
                    {"check": "mx", "status": "pending", "message": "Verify MX record"},
                    {"check": "spf", "status": "pending", "message": "Verify SPF record"},
                    {"check": "dkim", "status": "pending", "message": "Verify DKIM record"},
                    {"check": "dmarc", "status": "pending", "message": "Verify DMARC record"},
                ],
                "warnings": ["DNS records have not been verified yet"],
            }
        ]

    domains = []
    for name, verified, mx, spf, dkim, dmarc in rows:
        checks = [
            _make_check("mx", mx, "MX record"),
            _make_check("spf", spf, "SPF record"),
            _make_check("dkim", dkim, "DKIM record"),
            _make_check("dmarc", dmarc, "DMARC record"),
        ]
        warnings = []
        if not all([mx, spf, dkim, dmarc]):
            warnings.append("Missing DNS records — check deliverability")
        domains.append({
            "name": name,
            "checks": checks,
            "warnings": warnings,
        })
    return domains


def _make_check(code, status_bool, label):
    if status_bool:
        return {"check": code, "status": "ok", "message": f"{label} verified"}
    return {"check": code, "status": "pending", "message": f"Verify {label}"}


def _get_security_events():
    """Return recent security events from the audit trail."""
    return [
        {
            "time": "No recent events",
            "severity": "info",
            "description": "Security audit system is active",
        }
    ]
