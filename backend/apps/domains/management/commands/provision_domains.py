"""Bring every hosted domain up to date: DKIM key, postmaster/abuse aliases, certificate list.

Run by the api entrypoint on every start (idempotent, no network). Re-running is
the supported way to repair a domain whose provisioning stopped half way.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

# Architectural exception: CLI developer tooling may import from platform.
# This is a management command only, never executed at runtime in production.
from backend.apps.domains.models import Domain
from backend.apps.domains.services.provisioning import ProvisioningService
from backend.apps.mail.services.postfix_runtime import PostfixRuntime


class Command(BaseCommand):
    help = 'Ensure DKIM keys, postmaster/abuse aliases and runtime files exist for every domain.'

    def add_arguments(self, parser) -> None:
        parser.add_argument('--verify', action='store_true', help='also run DNS verification')

    def handle(self, *args, **options) -> None:
        domains = list(Domain.objects.order_by('name'))
        if not domains:
            self.stdout.write('No domains yet; nothing to provision.')
        for domain in domains:
            result = ProvisioningService.add_domain(
                domain.name, verify=bool(options['verify']), actor='provision_domains'
            )
            state = ', '.join(f'{s.name}={s.status}' for s in result.steps)
            self.stdout.write(f'{domain.name}: {state}')
        PostfixRuntime.apply()
        self.stdout.write(self.style.SUCCESS('Runtime files published.'))
