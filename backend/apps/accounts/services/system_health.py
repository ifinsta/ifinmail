"""System health: everything that is wrong, pending or worth doing on this mail server.

Modelled on the checks mature self-hosted mail systems run (Mail-in-a-Box status checks,
mailcow's queue/container views) and on what Gmail, Yahoo and Microsoft require from senders
(SPF, DKIM, DMARC, forward-confirmed reverse DNS, TLS). Every check says what is wrong, how to
fix it, and gives the exact values to copy. Results are cached for a few minutes because most
checks ask public DNS; "Re-check now" refreshes them.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from django.core.cache import cache

from backend.config.env import primary_domain

logger = logging.getLogger('backend')

CACHE_KEY = 'system-health:report'
CACHE_SECONDS = 300

ERROR, WARNING, WAITING, UNKNOWN, INFO, OK = 'error', 'warning', 'waiting', 'unknown', 'info', 'ok'
_ORDER = {ERROR: 0, WARNING: 1, UNKNOWN: 2, WAITING: 3, INFO: 4, OK: 5}

GROUP_DELIVERY = 'Mail delivery'
GROUP_IDENTITY = 'Server identity'
GROUP_SERVER = 'Server'
GROUP_SECURITY = 'Security'

_QUEUE_FILE = os.environ.get('IFINMAIL_STATUS_DIR', '/var/lib/ifinmail/status') + '/mailq.json'
_OUTBOUND_PROBE = ('gmail-smtp-in.l.google.com', 25)


@dataclass
class HealthCheck:
    key: str
    group: str
    title: str
    state: str
    summary: str
    fix: str = ''
    values: list[tuple[str, str]] = field(default_factory=list)
    link: str = ''  # URL of the console page that fixes it
    link_label: str = ''


@dataclass
class HealthReport:
    checked_at: datetime
    checks: list[HealthCheck]

    def _with(self, *states: str) -> list[HealthCheck]:
        return sorted(
            (c for c in self.checks if c.state in states), key=lambda c: _ORDER[c.state]
        )

    @property
    def attention(self) -> list[HealthCheck]:
        return self._with(ERROR, WARNING, UNKNOWN)

    @property
    def waiting(self) -> list[HealthCheck]:
        return self._with(WAITING)

    @property
    def good(self) -> list[HealthCheck]:
        return self._with(OK, INFO)

    @property
    def errors(self) -> int:
        return sum(1 for c in self.checks if c.state == ERROR)

    @property
    def warnings(self) -> int:
        return sum(1 for c in self.checks if c.state in (WARNING, UNKNOWN))

    @property
    def badge(self) -> int:
        """Number shown next to "System health" in the sidebar."""
        return self.errors + self.warnings


def _url(name: str, **kwargs: str) -> str:
    from django.urls import NoReverseMatch, reverse

    try:
        return reverse(name, kwargs=kwargs or None)
    except NoReverseMatch:
        return ''


def _check(fn, *args) -> list[HealthCheck]:  # noqa: ANN001
    """Run one check; a crash becomes an "unknown" row instead of breaking the page."""
    try:
        result = fn(*args)
    except Exception:
        logger.exception('System health check %s failed', getattr(fn, '__name__', fn))
        name = getattr(fn, '__name__', 'check').removeprefix('_').replace('_', ' ')
        return [HealthCheck(name, GROUP_SERVER, name.capitalize(), UNKNOWN, 'This check failed.')]
    return result if isinstance(result, list) else [result]


# ── Mail delivery ──────────────────────────────────────────────────────────────────────────


def _inbound_smtp(mail_hostname: str) -> HealthCheck:
    from backend.apps.core.platform.services.deliverability import DeliverabilityService

    result = DeliverabilityService._check_port25(mail_hostname)
    state = {'pass': OK, 'warn': WARNING}.get(result.get('status'), ERROR)
    return HealthCheck(
        'inbound-smtp',
        GROUP_DELIVERY,
        'Receiving mail (port 25)',
        state,
        'The mail server answers on port 25.' if state == OK else result.get('detail', ''),
        result.get('fix') or '',
    )


def _outbound_smtp() -> HealthCheck:
    host, port = _OUTBOUND_PROBE
    title = 'Sending mail (outbound port 25)'
    try:
        with socket.create_connection((host, port), timeout=6) as sock:
            sock.settimeout(6)
            banner = sock.recv(256).decode('utf-8', 'replace')
    except OSError as exc:
        return HealthCheck(
            'outbound-smtp',
            GROUP_DELIVERY,
            title,
            ERROR,
            f'This server cannot open connections to other mail servers on port 25 ({exc}).',
            'Many VPS providers block outbound port 25 on new servers. Ask your provider to '
            'unblock it; until then no mail can leave this server.',
        )
    state = OK if banner.startswith('220') else WARNING
    return HealthCheck(
        'outbound-smtp',
        GROUP_DELIVERY,
        title,
        state,
        'Other mail servers can be reached on port 25.'
        if state == OK
        else 'Port 25 opened but the remote server answered unexpectedly.',
    )


def _mail_queue() -> HealthCheck:
    title = 'Mail queue'
    try:
        with open(_QUEUE_FILE, encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return HealthCheck(
            'mail-queue', GROUP_DELIVERY, title, UNKNOWN,
            'The mail server has not reported its queue yet.',
            'It reports every minute; if this stays, check that the postfix container runs.',
        )
    if time.time() - float(data.get('updated', 0)) > 600:
        return HealthCheck(
            'mail-queue', GROUP_DELIVERY, title, WARNING,
            'The queue report is more than 10 minutes old.',
            'Check that the postfix container is running (make ps).',
        )
    deferred = int(data.get('deferred', 0))
    held = int(data.get('hold', 0))
    oldest_h = int(data.get('oldest_deferred_seconds', 0)) // 3600
    if deferred == 0 and held == 0:
        return HealthCheck(
            'mail-queue', GROUP_DELIVERY, title, OK,
            f'Nothing waiting ({int(data.get("active", 0))} message(s) being delivered now).',
        )
    state = ERROR if deferred > 50 or oldest_h >= 24 else WARNING
    return HealthCheck(
        'mail-queue', GROUP_DELIVERY, title, state,
        f'{deferred} message(s) are waiting to be retried'
        + (f', the oldest for {oldest_h} hour(s)' if oldest_h else '')
        + (f'; {held} held' if held else '')
        + '.',
        'Deferred mail is retried automatically for 5 days. A growing queue usually means a '
        'receiving server rejects us: check reverse DNS, blocklists and the logs (make logs).',
    )


def _blocklists(server_ip: str) -> HealthCheck:
    from backend.apps.core.platform.services.deliverability import DeliverabilityService

    result = DeliverabilityService._check_blacklists(server_ip)
    listed = [rbl for rbl, v in result.get('listings', {}).items() if v.get('listed')]
    if listed:
        return HealthCheck(
            'blocklists', GROUP_DELIVERY, 'Blocklists', ERROR,
            f'{server_ip} is listed on: {", ".join(listed)}.',
            'Mail from this server is likely rejected. Follow each list\'s delisting page; '
            'common causes are a previous owner of the IP or a compromised account.',
        )
    state = OK if result.get('status') == 'pass' else UNKNOWN
    return HealthCheck(
        'blocklists', GROUP_DELIVERY, 'Blocklists', state,
        f'{server_ip} is not on {len(result.get("listings", {}))} checked blocklists.'
        if state == OK
        else result.get('detail', 'Blocklists could not be checked.'),
        '' if state == OK else (result.get('fix') or ''),
    )


# ── Server identity ────────────────────────────────────────────────────────────────────────


def _public(name: str, rtype: str) -> list[str] | None:
    from backend.apps.core.platform.services.deliverability import _resolve

    for resolver in ('1.1.1.1', '8.8.8.8'):
        answers = _resolve(name, rtype, resolver)
        if answers is not None:
            return [a.rstrip('.').lower() for a in answers]
    return None


def _hostname_resolves(mail_hostname: str, server_ip: str) -> HealthCheck:
    title = f'{mail_hostname} points here'
    answers = _public(mail_hostname, 'A')
    if answers is None:
        return HealthCheck('mail-host-a', GROUP_IDENTITY, title, UNKNOWN, 'Could not look it up.')
    if server_ip in answers:
        return HealthCheck('mail-host-a', GROUP_IDENTITY, title, OK, f'{mail_hostname} → {server_ip}.')
    return HealthCheck(
        'mail-host-a', GROUP_IDENTITY, title, ERROR,
        f'{mail_hostname} resolves to {", ".join(answers) or "nothing"}, not {server_ip}.',
        'Other servers find this server by this name; it must point at this server.',
        [('A record', f'{mail_hostname} → {server_ip}')],
    )


def _reverse_dns(mail_hostname: str, server_ip: str) -> HealthCheck:
    import dns.reversename

    title = 'Reverse DNS (PTR)'
    fix = (
        'Set it in your VPS provider\'s control panel (often under Networking or the IP '
        'address), not at your domain registrar. Gmail, Yahoo and Microsoft reject or '
        'spam-folder mail from addresses without matching reverse DNS.'
    )
    values = [('IP address', server_ip), ('Reverse DNS name', mail_hostname)]
    ptr = _public(dns.reversename.from_address(server_ip).to_text(), 'PTR')
    if ptr is None:
        return HealthCheck('ptr', GROUP_IDENTITY, title, UNKNOWN, 'Could not look it up.', '', values)
    if mail_hostname not in ptr:
        return HealthCheck(
            'ptr', GROUP_IDENTITY, title, ERROR,
            f'{server_ip} points back to {", ".join(ptr) or "nothing"}, not {mail_hostname}.',
            fix, values,
        )
    forward = _public(mail_hostname, 'A') or []
    if server_ip not in forward:
        return HealthCheck(
            'ptr', GROUP_IDENTITY, title, WARNING,
            f'Reverse DNS names {mail_hostname}, but that name does not point back to {server_ip}.',
            'Receiving servers check both directions (forward-confirmed reverse DNS).',
        )
    return HealthCheck(
        'ptr', GROUP_IDENTITY, title, OK, f'{server_ip} ↔ {mail_hostname}, both directions match.'
    )


def _certificate(mail_hostname: str) -> HealthCheck:
    from backend.apps.core.platform.services.tls import TLSService

    title = 'TLS certificate'
    cert = TLSService.active_certificate()
    link = {'link': _url('accounts:certificates'), 'link_label': 'TLS certificates'}
    if cert is None:
        return HealthCheck(
            'tls', GROUP_IDENTITY, title, ERROR, 'No certificate is installed.',
            'Open TLS certificates and issue one.', **link,
        )
    if cert.self_signed:
        return HealthCheck(
            'tls', GROUP_IDENTITY, title, WAITING,
            'A temporary self-signed certificate is in use; mail apps and browsers warn about it.',
            'Let\'s Encrypt replaces it automatically once DNS points here.', **link,
        )
    if not cert.covers(mail_hostname):
        return HealthCheck(
            'tls', GROUP_IDENTITY, title, ERROR,
            f'The certificate does not cover {mail_hostname}.', 'Issue a new one.', **link,
        )
    days = cert.days_left
    if days <= 7:
        state = ERROR
    elif days <= 21:
        state = WARNING
    else:
        state = OK
    return HealthCheck(
        'tls', GROUP_IDENTITY, title, state,
        f'Issued by {cert.issuer}, valid for {days} more days.',
        '' if state == OK else 'It renews automatically 30 days before expiry; renewal seems '
        'to be failing. Open TLS certificates and renew now.',
        **({} if state == OK else link),
    )


# ── Per-domain DNS ─────────────────────────────────────────────────────────────────────────


def _domain_checks(domain: str, mail_hostname: str, server_ip: str) -> list[HealthCheck]:
    from backend.apps.dns.services.delegation import DelegationService
    from backend.apps.dns.services.zones import ZoneService
    from backend.apps.dns.types.zones import ZoneMode
    from backend.apps.domains.services.verification import DomainVerificationService
    from backend.apps.domains.types.provisioning import CheckStatus

    group = domain
    checks: list[HealthCheck] = []
    zone = ZoneService.ensure(domain)
    authoritative = zone.mode == ZoneMode.AUTHORITATIVE.value
    dns_link = (
        {'link': _url('dns:server'), 'link_label': 'DNS server'}
        if authoritative
        else {'link': _url('dns:config'), 'link_label': 'Domains & DNS'}
    )

    if authoritative:
        status = DelegationService.check(domain)
        ns_values = [('Nameserver', ns) for ns in status.expected_ns]
        ns_values += [
            (f'Glue: {ns}', server_ip)
            for ns in status.expected_ns
            if ns == domain or ns.endswith(f'.{domain}')
        ]
        if status.delegated:
            checks.append(HealthCheck('nameservers', group, 'Nameservers', OK, 'Delegated to this server.'))
        else:
            checks.append(HealthCheck(
                'nameservers', group, 'Nameservers',
                UNKNOWN if status.delegated is None else ERROR,
                f'The registrar lists {", ".join(status.public_ns) or "no nameservers"}.',
                'At your registrar, add the glue records, then set the nameservers below.',
                ns_values, **dns_link,
            ))
        ds = ZoneService.ds_records(domain)
        ds_values = [('DS record', d.text()) for d in ds]
        if not ds:
            checks.append(HealthCheck('dnssec', group, 'DNSSEC', WAITING, 'The zone is being signed.'))
        elif status.ds_published:
            checks.append(HealthCheck('dnssec', group, 'DNSSEC', OK, 'Signed, and the registrar publishes the DS record.'))
        elif status.delegated:
            checks.append(HealthCheck(
                'dnssec', group, 'DNSSEC', WARNING,
                'The zone is signed, but the registrar does not publish its DS record yet.',
                'Add this DS record in the DNSSEC settings at your registrar (recommended: it '
                'protects your mail records from spoofing).',
                ds_values, **dns_link,
            ))
        else:
            checks.append(HealthCheck(
                'dnssec', group, 'DNSSEC', WAITING,
                'Add the DS record at your registrar once the nameserver change is live.',
                '', ds_values,
            ))

    result = DomainVerificationService.check(domain)
    labels = {
        'mx': ('MX record', 'Where other servers deliver mail for the domain.'),
        'spf': ('SPF', 'Which servers may send mail for the domain.'),
        'dkim': ('DKIM', 'The signature on outgoing mail.'),
        'dmarc': ('DMARC', 'What receivers do with mail that fails SPF and DKIM.'),
    }
    for key, (title, _what) in labels.items():
        check = getattr(result, key)
        if check.status == CheckStatus.PASS:
            state = OK
        elif check.status == CheckStatus.ERROR:
            state = UNKNOWN
        else:
            state = WAITING if authoritative and not _delegated_cached(checks) else ERROR
        checks.append(HealthCheck(
            key, group, title, state, check.detail or ('Published.' if state == OK else ''),
            '' if state in (OK, WAITING)
            else 'This server publishes it once the domain is delegated here.'
            if authoritative
            else 'Add the record shown on the domain page at your DNS provider.',
            **({} if state == OK else dns_link),
        ))
        if key == 'dmarc' and state == OK:
            policy = _dmarc_policy(domain)
            if policy == 'none':
                checks[-1] = HealthCheck(
                    'dmarc', group, 'DMARC', WARNING,
                    'DMARC is published with p=none: spoofed mail is still delivered.',
                    'Once reports show your own mail passes, raise the policy to quarantine.',
                )

    checks.append(_mta_sts(domain, group))
    checks.append(_tls_rpt(domain, group))
    checks.append(_role_addresses(domain, group))
    return checks


def _delegated_cached(checks: list[HealthCheck]) -> bool:
    return any(c.key == 'nameservers' and c.state == OK for c in checks)


def _dmarc_policy(domain: str) -> str:
    for record in _public(f'_dmarc.{domain}', 'TXT') or []:
        text = record.replace('"', '').replace(' ', '').lower()
        if text.startswith('v=dmarc1'):
            for part in text.split(';'):
                if part.startswith('p='):
                    return part[2:]
    return ''


def _mta_sts(domain: str, group: str) -> HealthCheck:
    from backend.apps.mail.services.mta_sts import MtaStsService

    mode = MtaStsService.mode()
    if mode == 'enforce':
        return HealthCheck('mta-sts', group, 'MTA-STS', OK, 'Enforced: senders must use TLS to reach you.')
    return HealthCheck(
        'mta-sts', group, 'MTA-STS', INFO,
        f'Published in {mode} mode: senders report TLS problems but still deliver without TLS.',
        'After two weeks without TLS failure reports, switch MTA-STS to enforce.',
    )


def _tls_rpt(domain: str, group: str) -> HealthCheck:
    name = f'_smtp._tls.{domain}'
    records = _public(name, 'TXT')
    title = 'TLS reporting (TLS-RPT)'
    if records and any('v=tlsrptv1' in r.replace('"', '').lower() for r in records):
        return HealthCheck('tls-rpt', group, title, OK, 'Published: senders report TLS delivery problems.')
    return HealthCheck(
        'tls-rpt', group, title, INFO,
        'Not published. Optional: daily reports from large senders about TLS problems reaching you.',
        'Add this TXT record (as a custom record on the DNS server page, or at your DNS host).',
        [('TXT ' + name, f'v=TLSRPTv1; rua=mailto:postmaster@{domain}')],
    )


def _role_addresses(domain: str, group: str) -> HealthCheck:
    from backend.apps.mail.models import Alias, Mailbox

    title = 'postmaster@ and abuse@'
    mailboxes = {
        f'{local}@{name}'.lower()
        for local, name in Mailbox.objects.values_list('local_part', 'domain__name')
    }
    hosted = set(Mailbox.objects.values_list('domain__name', flat=True).distinct())
    problems = []
    for role in ('postmaster', 'abuse'):
        address = f'{role}@{domain}'
        if address in mailboxes:
            continue
        targets = [
            d.strip().lower()
            for row in Alias.objects.filter(source=address).values_list('destination', flat=True)
            for d in row.split(',')
            if d.strip()
        ]
        if not targets:
            problems.append(f'{address} does not exist')
            continue
        dead = [t for t in targets if t.split('@')[-1] in hosted and t not in mailboxes]
        if len(dead) == len(targets):
            problems.append(f'{address} forwards to {", ".join(dead)}, which has no mailbox')
    if not problems:
        return HealthCheck('role-addresses', group, title, OK, 'Both deliver to a mailbox.')
    return HealthCheck(
        'role-addresses', group, title, WARNING,
        '; '.join(problems) + '.',
        'Mail providers and RFC 2142 expect these addresses to reach a person (DMARC reports go '
        'to postmaster@). Point them at a mailbox you read under Settings → Aliases.',
        link=_url('accounts:aliases'), link_label='Aliases',
    )


# ── Server ─────────────────────────────────────────────────────────────────────────────────


def _services() -> HealthCheck:
    from backend.apps.dns.services.delegation import dns_server_alive
    from backend.apps.dns.services.server import DNSServerConfig

    down = []
    for name, host, port in (
        ('Postfix (SMTP)', 'postfix', 25),
        ('Dovecot (IMAP)', 'dovecot', 993),
        ('Rspamd (spam filter)', 'rspamd', 11332),  # milter port postfix uses
        ('Redis', os.environ.get('REDIS_HOST', 'redis'), 6379),
    ):
        try:
            socket.create_connection((host, port), timeout=3).close()
        except OSError:
            down.append(name)
    try:
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
    except Exception:
        down.append('PostgreSQL')
    if DNSServerConfig.enabled():
        alive, _detail = dns_server_alive()
        if not alive:
            down.append('DNS server')
    if not down:
        return HealthCheck('services', GROUP_SERVER, 'Services', OK, 'All mail, spam, database and DNS services answer.')
    return HealthCheck(
        'services', GROUP_SERVER, 'Services', ERROR,
        f'Not answering: {", ".join(down)}.',
        'Check the containers with "make ps" and their logs with "make logs" in the install '
        'directory.',
    )


def _disk() -> HealthCheck:
    path = '/var/mail/vhosts' if os.path.isdir('/var/mail/vhosts') else '/'
    usage = shutil.disk_usage(path)
    free_pct = usage.free * 100 / usage.total
    free_gb = usage.free / 1024**3
    state = ERROR if free_pct < 10 else WARNING if free_pct < 20 else OK
    return HealthCheck(
        'disk', GROUP_SERVER, 'Disk space', state,
        f'{free_gb:.1f} GB free ({free_pct:.0f}%).',
        '' if state == OK else 'Mail stops being accepted when the disk is full. Remove old '
        'backups or grow the disk.',
    )


def _memory() -> HealthCheck:
    info = {}
    with open('/proc/meminfo', encoding='utf-8') as handle:
        for line in handle:
            key, _, rest = line.partition(':')
            info[key] = int(rest.split()[0]) if rest.split() else 0
    total, available = info.get('MemTotal', 0), info.get('MemAvailable', 0)
    if not total:
        return HealthCheck('memory', GROUP_SERVER, 'Memory', UNKNOWN, 'Could not read memory use.')
    pct = available * 100 / total
    state = ERROR if pct < 10 else WARNING if pct < 20 else OK
    return HealthCheck(
        'memory', GROUP_SERVER, 'Memory', state,
        f'{available / 1024**2:.1f} GB of {total / 1024**2:.1f} GB available ({pct:.0f}%).',
        '' if state == OK else 'Services may be stopped by the system when memory runs out. '
        'Add swap or memory, or stop other programs on the server.',
    )


def _backups() -> HealthCheck:
    from backend.apps.core.platform.services.runtime import read_runtime_file

    raw = (read_runtime_file('last-backup-at') or '').strip()
    title = 'Backups'
    if not raw:
        return HealthCheck(
            'backups', GROUP_SERVER, title, WAITING,
            'No backup has completed yet. The first runs tonight at 03:15 (server time).',
            'To run one now: "make backup" in the install directory.',
        )
    try:
        when = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except ValueError:
        return HealthCheck('backups', GROUP_SERVER, title, UNKNOWN, f'Unreadable backup time: {raw}.')
    hours = (datetime.now(UTC) - when).total_seconds() / 3600
    state = OK if hours < 30 else WARNING if hours < 72 else ERROR
    return HealthCheck(
        'backups', GROUP_SERVER, title, state,
        f'Last successful backup {int(hours)} hour(s) ago.',
        '' if state == OK else 'The daily backup is not succeeding. See '
        '/var/log/ifinmail-backup.log on the server.',
    )


def _background_jobs() -> HealthCheck:
    from backend.apps.core.services import SystemSettings
    from backend.apps.core.types import SettingKey

    raw = SystemSettings.get(SettingKey.LAST_VERIFY_AT)
    title = 'Background jobs'
    if not raw:
        return HealthCheck(
            'jobs', GROUP_SERVER, title, WAITING,
            'DNS re-verification has not run yet (it runs every 15 minutes).',
        )
    when = datetime.fromisoformat(str(raw))
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    minutes = (datetime.now(UTC) - when).total_seconds() / 60
    if minutes <= 40:
        return HealthCheck('jobs', GROUP_SERVER, title, OK, f'DNS last re-verified {int(minutes)} minute(s) ago.')
    return HealthCheck(
        'jobs', GROUP_SERVER, title, WARNING,
        f'DNS was last re-verified {int(minutes // 60)} hour(s) ago; it should run every 15 minutes.',
        'The worker or beat container may be stopped: check "make ps".',
    )


def _software_version() -> HealthCheck:
    from backend.apps.core.platform.services.updates import UpdateService

    title = 'Software version'
    status = UpdateService.status()
    if not status.enabled:
        return HealthCheck(
            'version', GROUP_SERVER, title, INFO,
            f'Running {status.current}. Update checks are switched off.',
            'Switch them on at the bottom of this page to hear about new releases.',
        )
    stale = True
    if status.checked_at:
        checked = datetime.fromisoformat(status.checked_at)
        stale = (datetime.now(UTC) - checked).total_seconds() > 6 * 3600
    if stale:
        status = UpdateService.check()
    install_dir = os.environ.get('IFINMAIL_INSTALL_DIR', '') or 'the install directory'
    if status.available:
        return HealthCheck(
            'version', GROUP_SERVER, title, WARNING,
            f'{status.latest} is available; this server runs {status.current}.',
            'Updating takes a database snapshot first and rolls back by itself if the new version '
            'does not come up healthy. Run on the server:',
            [('Update', f'cd {install_dir} && sudo make update'),
             ('Undo the update', f'cd {install_dir} && sudo make rollback')],
            link=status.changes_url, link_label=f'What changed in {status.latest}',
        )
    if status.error and not status.latest:
        return HealthCheck('version', GROUP_SERVER, title, UNKNOWN, f'Running {status.current}. {status.error}')
    return HealthCheck(
        'version', GROUP_SERVER, title, OK,
        f'Running {status.current}, the latest release.'
        if status.latest
        else f'Running {status.current}; no release published yet.',
    )


# ── Security ───────────────────────────────────────────────────────────────────────────────


def _security() -> list[HealthCheck]:
    from backend.apps.accounts.models import MailUser, TOTPDevice
    from backend.apps.core.services import SystemSettings
    from backend.apps.core.types import SettingKey

    checks = []
    from django.db.models import Q

    admins = list(MailUser.objects.filter(Q(is_staff=True) | Q(is_superuser=True), is_active=True))
    printed = [u.email for u in admins if getattr(u, 'password_change_required', False)]
    checks.append(
        HealthCheck(
            'installer-password', GROUP_SECURITY, 'Installer password', ERROR,
            f'{", ".join(printed)} still uses the password the installer printed.',
            'Sign in with it once; you will be asked to choose a new one.',
        )
        if printed
        else HealthCheck('installer-password', GROUP_SECURITY, 'Installer password', OK, 'Replaced.')
    )
    enrolled = set(
        TOTPDevice.objects.filter(user__in=admins, verified=True).values_list('user_id', flat=True)
    )
    without = [u.email for u in admins if u.pk not in enrolled]
    from backend.apps.accounts.services.mfa import TOTPService

    enforced = TOTPService.enforced()
    title = 'Two-factor sign-in'
    if without and enforced:
        two_factor = HealthCheck(
            'admin-2fa', GROUP_SECURITY, title, WARNING,
            f'Required, and not yet set up for: {", ".join(without)}.',
            'They are sent to set it up at their next sign-in.',
            link=_url('accounts:mfa_setup'), link_label='Set up two-factor',
        )
    elif without:
        two_factor = HealthCheck(
            'admin-2fa', GROUP_SECURITY, title, WARNING,
            f'Optional, and not set up for: {", ".join(without)}.',
            'A stolen password alone can open the console. Set MFA_ENFORCEMENT=required in '
            'the install directory\'s provisioning/.env and restart to make it mandatory.',
            link=_url('accounts:mfa_setup'), link_label='Set up two-factor',
        )
    elif not enforced:
        two_factor = HealthCheck(
            'admin-2fa', GROUP_SECURITY, title, INFO,
            'Every administrator uses it, but it is optional.',
            'Set MFA_ENFORCEMENT=required so new administrators cannot skip it.',
        )
    else:
        two_factor = HealthCheck(
            'admin-2fa', GROUP_SECURITY, title, OK, 'Required, and every administrator uses it.'
        )
    checks.append(two_factor)
    if SystemSettings.get_bool(SettingKey.REGISTRATION_OPEN, False):
        checks.append(HealthCheck(
            'registration', GROUP_SECURITY, 'Public sign-up', INFO,
            'Anyone can create a mailbox on this server.',
            'Turn it off under Settings → Mailboxes unless you mean to run an open service.',
        ))
    return checks


# ── Report ─────────────────────────────────────────────────────────────────────────────────


def _collect() -> HealthReport:
    from backend.apps.dns.services.server import DNSServerConfig
    from backend.apps.domains.models import Domain

    domain = primary_domain()
    mail_hostname = DNSServerConfig.mail_hostname() or f'mail.{domain}'
    server_ip = DNSServerConfig.server_ipv4()

    checks: list[HealthCheck] = []
    checks += _check(_inbound_smtp, mail_hostname)
    checks += _check(_outbound_smtp)
    checks += _check(_mail_queue)
    if server_ip:
        checks += _check(_blocklists, server_ip)
        checks += _check(_hostname_resolves, mail_hostname, server_ip)
        checks += _check(_reverse_dns, mail_hostname, server_ip)
    checks += _check(_certificate, mail_hostname)
    names = list(Domain.objects.order_by('name').values_list('name', flat=True)) or [domain]
    for name in names:
        checks += _check(_domain_checks, name, mail_hostname, server_ip)
    checks += _check(_services)
    checks += _check(_disk)
    checks += _check(_memory)
    checks += _check(_backups)
    checks += _check(_background_jobs)
    checks += _check(_software_version)
    checks += _check(_security)
    return HealthReport(checked_at=datetime.now(UTC), checks=checks)


class SystemHealth:
    @staticmethod
    def report(refresh: bool = False) -> HealthReport:
        cached = None if refresh else cache.get(CACHE_KEY)
        if cached is not None:
            return cached
        report = _collect()
        cache.set(CACHE_KEY, report, CACHE_SECONDS)
        return report

    @staticmethod
    def cached_badge() -> int | None:
        """Issue count for the sidebar, from the last report only (never runs the checks)."""
        cached = cache.get(CACHE_KEY)
        return cached.badge if cached is not None else None
