"""Verify the audit trail's hash chain and print its head (exit 1 when broken)."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from backend.apps.core.platform.services.audit import AuditService


class Command(BaseCommand):
    help = 'Verify the audit trail hash chain; prints the head so it can be recorded off-host.'

    def handle(self, *args: object, **options: object) -> None:
        result = AuditService.verify_chain()
        self.stdout.write(
            f'checked={result["checked"]} head={result["head_seq"] or 0}:{result["head_hash"]}'
        )
        if not result['ok']:
            error = result['error'] or {}
            raise CommandError(f'chain broken at seq {error.get("seq")} ({error.get("reason")})')
        self.stdout.write(self.style.SUCCESS('Audit chain intact.'))
