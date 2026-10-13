"""One pipeline for adding a domain, used by the setup wizard and the console.

Steps are idempotent and independent: a failure in one is recorded and the rest
still run, so re-running the pipeline repairs whatever is missing. Nothing here
waits for DNS propagation; verification runs once now and then on a schedule.
"""

from __future__ import annotations

import logging
import os
import re

from django.db import IntegrityError

from backend.apps.core.platform.services.audit import AuditService
from backend.apps.core.platform.services.certificates import CertificateService
from backend.apps.core.services import SystemSettings
from backend.apps.core.types import SettingKey

from ..models import Domain
from ..types.provisioning import ProvisionResult, ProvisionStep, StepStatus
from .dkim import DKIMService
from .verification import DomainVerificationService

logger = logging.getLogger('backend')

_DOMAIN_RE = re.compile(r'^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$')
_SYSTEM_ALIASES = ('postmaster', 'abuse')


class DomainProvisioningError(ValueError):
    """The domain name is unusable (message is safe to show)."""


def normalise_domain(name: str) -> str:
    name = re.sub(r'^https?://', '', (name or '').strip().lower()).rstrip('.')
    if not _DOMAIN_RE.match(name):
        raise DomainProvisioningError('Enter a valid domain name such as example.com.')
    return name


class ProvisioningService:
    @staticmethod
    def admin_destination() -> str:
        """Where postmaster@/abuse@ mail should land, or '' if unknown."""
        configured = os.environ.get('ADMIN_EMAIL', '').strip().lower()
        if configured:
            return configured
        from backend.apps.accounts.models import MailUser

        admin = (
            MailUser.objects.filter(is_active=True, is_staff=True).order_by('created_at').first()
        )
        return admin.email if admin else ''

    @staticmethod
    def _step_database(
        domain_name: str, ip_address: str | None
    ) -> tuple[Domain, bool, ProvisionStep]:
        try:
            domain, created = Domain.objects.get_or_create(name=domain_name)
        except IntegrityError:  # concurrent creation: take the winner's row
            domain, created = Domain.objects.get(name=domain_name), False
        if ip_address and domain.ip_address != ip_address:
            domain.ip_address = ip_address
            domain.save(update_fields=['ip_address'])
        detail = 'Domain added' if created else 'Domain already present'
        return domain, created, ProvisionStep('Domain', StepStatus.OK, detail)

    @staticmethod
    def _step_dkim(domain: Domain) -> ProvisionStep:
        try:
            _, created = DKIMService.ensure(domain)
        except Exception as exc:
            logger.exception('DKIM provisioning failed for %s', domain.name)
            return ProvisionStep('DKIM key', StepStatus.ERROR, str(exc))
        return ProvisionStep(
            'DKIM key', StepStatus.OK, 'Key generated' if created else 'Key present'
        )

    @staticmethod
    def _step_aliases(domain: Domain) -> ProvisionStep:
        from backend.apps.mail.models import Alias

        destination = ProvisioningService.admin_destination()
        if not destination:
            return ProvisionStep(
                'postmaster/abuse', StepStatus.WARN, 'No administrator address to forward them to'
            )
        created = []
        try:
            for local in _SYSTEM_ALIASES:
                source = f'{local}@{domain.name}'
                if source == destination:
                    continue
                if Alias.objects.filter(source=source).exists():
                    continue
                from backend.apps.mail.models import Mailbox

                if Mailbox.objects.filter(local_part=local, domain=domain).exists():
                    continue
                Alias.objects.create(domain=domain, source=source, destination=destination)
                created.append(source)
        except Exception as exc:
            logger.exception('Alias provisioning failed for %s', domain.name)
            return ProvisionStep('postmaster/abuse', StepStatus.ERROR, str(exc))
        detail = f'Created {", ".join(created)}' if created else 'Already in place'
        return ProvisionStep('postmaster/abuse', StepStatus.OK, detail)

    @staticmethod
    def _step_authoritative_dns(domain: Domain, result: ProvisionResult) -> ProvisionStep | None:
        """Publish the zone from this server; ``None`` when the domain's DNS is hosted elsewhere."""
        from backend.apps.dns.services.server import DNSServerConfig
        from backend.apps.dns.services.zones import ZoneService
        from backend.apps.dns.types.zones import ZoneMode

        if not DNSServerConfig.enabled():
            return None
        try:
            zone = ZoneService.ensure(domain.name)
            if ZoneMode(zone.mode) != ZoneMode.AUTHORITATIVE:
                return None
            ZoneService.publish()
        except Exception as exc:
            logger.exception('Publishing the zone for %s failed', domain.name)
            return ProvisionStep('DNS records', StepStatus.ERROR, str(exc))
        result.dns_records = [
            {
                'type': r.type,
                'name': r.name,
                'value': f'{r.priority} {r.value}' if r.type == 'MX' else r.value,
            }
            for r in ZoneService.managed_records(domain.name)
        ]
        result.nameservers = DNSServerConfig.ns_hosts()
        return ProvisionStep(
            'DNS records',
            StepStatus.MANUAL,
            "Published by this server. Set the domain's nameservers to "
            + ', '.join(result.nameservers)
            + ' at your registrar.',
        )

    @staticmethod
    def _step_dns(domain: Domain, result: ProvisionResult) -> ProvisionStep:
        from backend.apps.dns.services import PROVIDER_MAP, DNSService

        authoritative = ProvisioningService._step_authoritative_dns(domain, result)
        if authoritative is not None:
            return authoritative

        server_ip = domain.ip_address or DNSService.get_server_ip()
        records = DNSService.build_records(domain.name, server_ip, ip_address=domain.ip_address)
        result.dns_records = [
            {
                'type': r.type,
                'name': r.name,
                'value': f'{r.priority} {r.value}' if r.type == 'MX' else r.value,
            }
            for r in records
        ]
        if DNSService.has_placeholder(records):
            return ProvisionStep('DNS records', StepStatus.ERROR, 'DKIM key is not available yet')
        config = None
        try:
            config = DNSService.get_first_config()
        except Exception:
            logger.debug('No DNS provider configuration readable', exc_info=True)
        if config is None or config.provider not in PROVIDER_MAP:
            return ProvisionStep(
                'DNS records',
                StepStatus.MANUAL,
                'No DNS provider connected: add the records below at your DNS host',
            )
        provider = DNSService.get_provider(config.provider)
        if provider is None:
            return ProvisionStep(
                'DNS records', StepStatus.ERROR, 'Stored provider credentials unreadable'
            )
        try:
            outcome = provider.configure_domain(domain.name, records)
        except Exception as exc:
            logger.exception('DNS push failed for %s', domain.name)
            return ProvisionStep('DNS records', StepStatus.ERROR, str(exc))
        status = StepStatus.OK if outcome.success else StepStatus.WARN
        return ProvisionStep('DNS records', status, outcome.message)

    @staticmethod
    def _step_certificates() -> ProvisionStep:
        try:
            hosts = CertificateService.sync()
        except Exception as exc:
            logger.exception('Certificate host list could not be written')
            return ProvisionStep('Certificates', StepStatus.ERROR, str(exc))
        return ProvisionStep(
            'Certificates', StepStatus.OK, f'Queued {len(hosts)} hostnames for the next issuance'
        )

    @staticmethod
    def _step_verify(domain: Domain, result: ProvisionResult) -> ProvisionStep:
        try:
            result.verification = DomainVerificationService.verify(domain)
        except Exception as exc:
            logger.exception('Verification failed for %s', domain.name)
            return ProvisionStep('Verification', StepStatus.ERROR, str(exc))
        if result.verification.accepts_mail:
            return ProvisionStep(
                'Verification', StepStatus.OK, 'MX points at this server; mail is accepted'
            )
        return ProvisionStep(
            'Verification', StepStatus.WARN, 'DNS is not ready yet; it is re-checked automatically'
        )

    @staticmethod
    def add_domain(
        name: str,
        *,
        ip_address: str | None = None,
        actor: str | None = None,
        verify: bool = True,
    ) -> ProvisionResult:
        domain_name = normalise_domain(name)
        domain, created, step = ProvisioningService._step_database(domain_name, ip_address)
        result = ProvisionResult(domain=domain_name, created=created, steps=[step])
        if not SystemSettings.get(SettingKey.MTA_STS_MODE):
            SystemSettings.set(SettingKey.MTA_STS_MODE, 'testing')
        result.steps.append(ProvisioningService._step_dkim(domain))
        result.steps.append(ProvisioningService._step_aliases(domain))
        result.steps.append(ProvisioningService._step_dns(domain, result))
        result.steps.append(ProvisioningService._step_certificates())
        if verify:
            result.steps.append(ProvisioningService._step_verify(domain, result))
        steps = ', '.join(f'{s.name}={s.status}' for s in result.steps)
        # A person's request, a new domain, or a different outcome than last time is worth a
        # line; the scheduled re-check that finds nothing changed is not (it was 27% of the log).
        known = SystemSettings.get(SettingKey.PROVISION_SIGNATURES, {})
        known = known if isinstance(known, dict) else {}
        if created or actor or known.get(domain_name) != steps:
            AuditService.record(
                action='domain_provisioned',
                user=actor,
                detail=f'{domain_name} created={created} {steps}',
            )
        if known.get(domain_name) != steps:
            SystemSettings.set(SettingKey.PROVISION_SIGNATURES, {**known, domain_name: steps})
        return result

    @staticmethod
    def remove_domain(name: str, *, actor: str | None = None) -> bool:
        from backend.apps.mail.models import Mailbox

        domain = Domain.objects.filter(name=normalise_domain(name)).first()
        if domain is None:
            return False
        if Mailbox.objects.filter(domain=domain).exists():
            raise DomainProvisioningError('Remove the mailboxes on this domain first.')
        domain.delete()  # aliases and DKIM keys cascade
        CertificateService.sync()
        AuditService.record(action='domain_removed', user=actor, detail=name)
        return True
