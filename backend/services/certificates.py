"""Certificate host list shared with the certbot container.

One certificate (named after the mail hostname) carries every name the server
must present: the mail hostname plus, for each domain, ``mta-sts.``,
``autoconfig.`` and ``autodiscover.``, plus the domain itself. This service writes that list; the
certbot container reads it and (re)issues the certificate when it changes.
"""

from __future__ import annotations

import os

from backend.services.runtime import write_runtime_file

HOSTS_FILE = 'cert-hosts.txt'
_PREFIXES = ('mta-sts', 'autoconfig', 'autodiscover')
# The apex name is kept too: the certificate originally covered it and certbot
# replaces (not merges) the name list when it re-issues.


class CertificateService:
    @staticmethod
    def mail_hostname() -> str:
        return os.environ.get('MAIL_HOSTNAME', '').strip().lower()

    @staticmethod
    def hosts_for(domain_names: list[str]) -> list[str]:
        """Mail hostname first (it names the certificate), then per-domain hosts, sorted."""
        primary = CertificateService.mail_hostname()
        hosts = {d.strip().lower() for d in domain_names}
        hosts |= {f'{prefix}.{d.strip().lower()}' for d in domain_names for prefix in _PREFIXES}
        ordered = sorted(hosts)
        return ([primary] if primary else []) + ordered

    @staticmethod
    def sync(domain_names: list[str] | None = None) -> list[str]:
        """Write the desired host list and return it."""
        if domain_names is None:
            from backend.apps.domains.models import Domain

            domain_names = list(Domain.objects.order_by('name').values_list('name', flat=True))
        hosts = CertificateService.hosts_for(domain_names)
        write_runtime_file(HOSTS_FILE, '\n'.join(hosts) + '\n')
        return hosts
