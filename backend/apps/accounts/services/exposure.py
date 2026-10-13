"""Exposure self-check: look at this server the way a stranger does, and say what they would see.

It requests the files scanners ask for, probes the ports that must never be open, checks the
certificate and headers, and talks to the mail ports the way an open-relay or address-harvesting
tool would (never sending a message: it stops at ``RCPT TO``). The targets are this server's own
names and address only; nothing here accepts a target from a person.

Results are stored (``SettingKey.EXPOSURE_LAST``) and shown on the Network page and in System
health. They run weekly and on request; the requests come from inside the stack, so the firewall
treats them as the server's own traffic and the scan ban never fires on the check itself.
"""

from __future__ import annotations

import http.client
import os
import socket
import ssl
import struct
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

OK, WARNING, ERROR = 'ok', 'warning', 'error'

# What scanners ask for. A 2xx for any of them is a file or page that should not be served.
SENSITIVE_PATHS = (
    '/.env',
    '/.env.production',
    '/.git/config',
    '/.git/HEAD',
    '/.aws/credentials',
    '/.ssh/id_rsa',
    '/.htpasswd',
    '/.DS_Store',
    '/wp-login.php',
    '/xmlrpc.php',
    '/phpinfo.php',
    '/server-status',
    '/actuator/env',
    '/backup.sql',
    '/dump.sql',
    '/database.sqlite',
    '/config.json',
    '/composer.json',
    '/package.json',
    '/docker-compose.yml',
    '/api/.env',
    '/admin/.env',
)
# Services that must not answer from outside (host-published by mistake would show here).
MUST_BE_CLOSED = {
    5432: 'PostgreSQL',
    6379: 'Redis',
    8000: 'the console (behind nginx only)',
    5232: 'the calendar server (behind nginx only)',
    11332: 'the spam filter milter',
    11333: 'the spam filter worker',
    11334: 'the spam filter web UI',
    10025: 'the internal mail relay',
    3306: 'MySQL',
    27017: 'MongoDB',
    9200: 'Elasticsearch',
    2375: 'the Docker API',
}
SECURITY_HEADERS = (
    'strict-transport-security',
    'x-content-type-options',
    'x-frame-options',
    'content-security-policy',
    'referrer-policy',
)
FRESH_DAYS = 10  # a result older than this is itself a warning
HTTPS_PORT = 443
SMTP_PORT = 25
SUBMISSION_PORT = 587
IMAP_PORT = 143
DNS_PORT = 53


@dataclass(frozen=True)
class Check:
    key: str
    group: str  # web | ports | tls | mail | dns
    title: str
    status: str  # ok | warning | error
    detail: str = ''


def own_names() -> list[str]:
    """This server's own public names: the mail host and the setup names of hosted domains."""
    names: list[str] = []
    host = os.environ.get('MAIL_HOSTNAME', '').strip().lower()
    if host:
        names.append(host)
    try:
        from backend.apps.domains.models import Domain

        for domain in Domain.objects.order_by('name').values_list('name', flat=True)[:2]:
            names += [f'autodiscover.{domain}', f'autoconfig.{domain}', f'mta-sts.{domain}']
    except Exception:  # no database yet (first boot): the mail host alone is still checked
        pass
    return list(dict.fromkeys(names))


def target_ip() -> str:
    """The address strangers connect to; the nginx service name when it cannot be reached."""
    configured = os.environ.get('SERVER_IP', '').strip()
    if configured:
        return configured
    host = os.environ.get('MAIL_HOSTNAME', '').strip()
    try:
        return socket.gethostbyname(host) if host else 'nginx'
    except OSError:
        return 'nginx'


def _fetch(
    ip: str, host: str, path: str, *, timeout: float = 6.0
) -> http.client.HTTPResponse | None:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE  # certificates are judged separately (check_tls)
    connection = http.client.HTTPSConnection(ip, HTTPS_PORT, timeout=timeout, context=context)
    try:
        connection.putrequest('GET', path, skip_host=True, skip_accept_encoding=True)
        connection.putheader('Host', host)
        connection.putheader('User-Agent', 'ifinmail-exposure-check')
        connection.endheaders()
        response = connection.getresponse()
        response.read(2048)
        return response
    except (OSError, http.client.HTTPException, ssl.SSLError):
        return None  # closed without an answer (444), reset or timed out: nothing was served
    finally:
        connection.close()


def check_paths(ip: str, names: list[str]) -> list[Check]:
    served: list[str] = []
    for name in names:
        for path in SENSITIVE_PATHS:
            response = _fetch(ip, name, path)
            if response is not None and 200 <= response.status < 300:
                served.append(f'{name}{path} ({response.status})')
    total = len(names) * len(SENSITIVE_PATHS)
    if served:
        return [
            Check(
                'paths',
                'web',
                'Sensitive files and admin pages',
                ERROR,
                f'{len(served)} of {total} requests were answered with content: '
                + ', '.join(served[:5]),
            )
        ]
    return [
        Check(
            'paths',
            'web',
            'Sensitive files and admin pages',
            OK,
            f'{total} scanner requests across {len(names)} name(s): none was served.',
        )
    ]


def check_headers(ip: str, host: str) -> list[Check]:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    connection = http.client.HTTPSConnection(ip, HTTPS_PORT, timeout=6, context=context)
    try:
        connection.putrequest('GET', '/accounts/login/', skip_host=True)
        connection.putheader('Host', host)
        connection.endheaders()
        response = connection.getresponse()
        response.read(1024)
        headers = [(k.lower(), v) for k, v in response.getheaders()]
    except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
        return [Check('headers', 'web', 'Security headers', WARNING, f'Could not read them: {exc}')]
    finally:
        connection.close()
    names = [k for k, _ in headers]
    missing = [h for h in SECURITY_HEADERS if h not in names]
    repeated = [h for h in ('strict-transport-security', 'x-frame-options') if names.count(h) > 1]
    server = next((v for k, v in headers if k == 'server'), '')
    leaks = any(ch.isdigit() for ch in server)
    problems = []
    if missing:
        problems.append('missing ' + ', '.join(missing))
    if repeated:
        problems.append('repeated ' + ', '.join(repeated))
    if leaks:
        problems.append(f'the server header names a version ({server})')
    if problems:
        return [Check('headers', 'web', 'Security headers', WARNING, '; '.join(problems) + '.')]
    return [
        Check(
            'headers',
            'web',
            'Security headers',
            OK,
            'All present, none repeated, no version shown.',
        )
    ]


def check_ports(ip: str) -> list[Check]:
    def probe(port: int) -> int | None:
        try:
            with socket.create_connection((ip, port), timeout=1.5):
                return port
        except OSError:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        opened = [p for p in pool.map(probe, MUST_BE_CLOSED) if p is not None]
    if opened:
        return [
            Check(
                'ports',
                'ports',
                'Internal services closed to the internet',
                ERROR,
                'Open from outside: ' + ', '.join(f'{p} ({MUST_BE_CLOSED[p]})' for p in opened),
            )
        ]
    return [
        Check(
            'ports',
            'ports',
            'Internal services closed to the internet',
            OK,
            f'{len(MUST_BE_CLOSED)} database, cache and internal ports: all closed.',
        )
    ]


def check_tls(ip: str, host: str) -> list[Check]:
    try:
        context = ssl.create_default_context()
        with (
            socket.create_connection((ip, HTTPS_PORT), timeout=6) as raw,
            context.wrap_socket(raw, server_hostname=host) as tls,
        ):
            cert = tls.getpeercert() or {}
            version = tls.version() or ''
    except ssl.SSLCertVerificationError as exc:
        return [
            Check(
                'tls', 'tls', 'Certificate', ERROR, f'Not trusted for {host}: {exc.verify_message}'
            )
        ]
    except (OSError, ssl.SSLError) as exc:
        return [
            Check('tls', 'tls', 'Certificate', WARNING, f'Could not complete a handshake: {exc}')
        ]
    not_after = (
        ssl.cert_time_to_seconds(str(cert.get('notAfter', ''))) if cert.get('notAfter') else 0
    )
    days = int((not_after - time.time()) // 86400) if not_after else -1
    if days < 0:
        return [Check('tls', 'tls', 'Certificate', ERROR, 'The certificate has expired.')]
    status = OK if days >= 14 and version in ('TLSv1.2', 'TLSv1.3') else WARNING
    return [
        Check(
            'tls',
            'tls',
            'Certificate',
            status,
            f'Trusted for {host}, {days} days left, {version}.'
            + ('' if status == OK else ' Renew soon or raise the minimum TLS version.'),
        )
    ]


def _smtp_dialogue(ip: str, port: int, lines: list[str], timeout: float = 8.0) -> str:
    """Send CRLF lines one at a time, return everything the server said (never sends DATA)."""
    said: list[str] = []
    try:
        with socket.create_connection((ip, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            said.append(sock.recv(4096).decode('latin-1'))
            for line in lines:
                sock.sendall(line.encode() + b'\r\n')
                time.sleep(0.4)
                said.append(sock.recv(8192).decode('latin-1'))
            sock.sendall(b'QUIT\r\n')
    except OSError:
        pass
    return ''.join(said)


def check_smtp(ip: str) -> list[Check]:
    out: list[Check] = []
    talk = _smtp_dialogue(
        ip,
        SMTP_PORT,
        [
            'EHLO exposure-check.invalid',
            'MAIL FROM:<probe@exposure-check.invalid>',
            'RCPT TO:<probe@example.net>',
        ],
    )
    if not talk:
        out.append(Check('smtp', 'mail', 'Open relay', WARNING, 'Port 25 did not answer.'))
    else:
        replies = [ln for ln in talk.splitlines() if ln[:1] in ('2', '4', '5') and ln[3:4] in ' -']
        # The last reply is the answer to RCPT TO: another domain is accepted only by a relay.
        accepted = bool(replies) and replies[-1].startswith(('250', '251'))
        out.append(
            Check(
                'relay',
                'mail',
                'Open relay',
                ERROR if accepted else OK,
                'An outsider was allowed to send to another domain: the server is an open relay.'
                if accepted
                else 'An unauthenticated message to another domain was refused.',
            )
        )
        vrfy = any(ln[4:].strip().upper().startswith('VRFY') for ln in replies if ln[:3] == '250')
        out.append(
            Check(
                'vrfy',
                'mail',
                'Address harvesting (VRFY)',
                WARNING if vrfy else OK,
                'VRFY is offered: a stranger can ask which mailboxes exist.'
                if vrfy
                else 'VRFY is not offered.',
            )
        )
    sub = _smtp_dialogue(ip, SUBMISSION_PORT, ['EHLO exposure-check.invalid'])
    if sub:
        offers_auth = any(
            ln[4:].upper().startswith('AUTH') for ln in sub.splitlines() if ln[:3] == '250'
        )
        out.append(
            Check(
                'submission',
                'mail',
                'Passwords only over TLS (587)',
                ERROR if offers_auth else OK,
                'SMTP AUTH is offered before STARTTLS: passwords could cross in clear text.'
                if offers_auth
                else 'AUTH is not offered until the connection is encrypted.',
            )
        )
    return out


def check_imap(ip: str) -> list[Check]:
    try:
        with socket.create_connection((ip, IMAP_PORT), timeout=6) as sock:
            sock.settimeout(6)
            banner = sock.recv(2048).decode('latin-1')
    except OSError:
        return [
            Check(
                'imap', 'mail', 'Passwords only over TLS (143)', WARNING, 'Port 143 did not answer.'
            )
        ]
    upper = banner.upper()
    plain = 'LOGINDISABLED' not in upper and (
        'AUTH=PLAIN' in upper or 'AUTH=LOGIN' in upper or ' LOGIN' in upper
    )
    return [
        Check(
            'imap',
            'mail',
            'Passwords only over TLS (143)',
            ERROR if plain else OK,
            'IMAP accepts a plain-text login before STARTTLS.'
            if plain
            else 'Plain-text login is disabled until the connection is encrypted.',
        )
    ]


def check_dns(ip: str) -> list[Check]:
    """A name server that answers recursive queries for strangers is a DDoS amplifier."""
    query = struct.pack('>HHHHHH', 0xBEEF, 0x0100, 1, 0, 0, 0)
    for label in ('example', 'com'):
        query += bytes([len(label)]) + label.encode()
    query += b'\x00' + struct.pack('>HH', 1, 1)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(3)
    try:
        sock.sendto(query, (ip, DNS_PORT))
        data, _ = sock.recvfrom(1500)
    except OSError:
        return [Check('dns', 'dns', 'Not an open resolver', OK, 'No answer to a recursive query.')]
    finally:
        sock.close()
    flags = struct.unpack('>H', data[2:4])[0]
    recursion_available, rcode = bool(flags & 0x0080), flags & 0x000F
    answers = struct.unpack('>H', data[6:8])[0]
    if recursion_available and rcode == 0 and answers > 0:
        return [
            Check(
                'dns',
                'dns',
                'Not an open resolver',
                ERROR,
                'The name server answered a recursive query for example.com: it can be abused to '
                'amplify attacks.',
            )
        ]
    return [Check('dns', 'dns', 'Not an open resolver', OK, 'Recursive queries are refused.')]


def run(now: datetime | None = None) -> dict[str, Any]:
    """Run every check against this server and return ``{at, ip, names, checks}``."""
    ip = target_ip()
    names = own_names() or ['localhost']
    checks: list[Check] = []
    for step in (
        lambda: check_paths(ip, names),
        lambda: check_headers(ip, names[0]),
        lambda: check_ports(ip),
        lambda: check_tls(ip, names[0]),
        lambda: check_smtp(ip),
        lambda: check_imap(ip),
        lambda: check_dns(ip),
    ):
        try:
            checks += step()
        except Exception as exc:  # one broken probe must not hide the others
            checks.append(Check('probe', 'web', 'A check could not run', WARNING, str(exc)[:200]))
    return {
        'at': (now or datetime.now(UTC)).isoformat(timespec='seconds'),
        'ip': ip,
        'names': names,
        'checks': [asdict(c) for c in checks],
    }


def store(result: dict[str, Any]) -> None:
    from backend.apps.core.services import SystemSettings
    from backend.apps.core.types import SettingKey

    SystemSettings.set(SettingKey.EXPOSURE_LAST, result)


def last() -> dict[str, Any] | None:
    from backend.apps.core.services import SystemSettings
    from backend.apps.core.types import SettingKey

    value = SystemSettings.get(SettingKey.EXPOSURE_LAST, None)
    return value if isinstance(value, dict) and value.get('checks') else None


def summarise(result: dict[str, Any] | None, now: datetime | None = None) -> dict[str, Any]:
    """What a page or health check says: counts, the failures, and whether it is stale."""
    if result is None:
        return {'state': 'never', 'ok': 0, 'warnings': [], 'errors': [], 'at': None, 'stale': False}
    checks = result.get('checks') or []
    errors = [c for c in checks if c.get('status') == ERROR]
    warnings = [c for c in checks if c.get('status') == WARNING]
    try:
        at = datetime.fromisoformat(str(result.get('at')))
    except ValueError:
        at = None
    stale = bool(at and (now or datetime.now(UTC)) - at > timedelta(days=FRESH_DAYS))
    state = 'error' if errors else 'warning' if warnings or stale else 'ok'
    return {
        'state': state,
        'ok': sum(1 for c in checks if c.get('status') == OK),
        'warnings': warnings,
        'errors': errors,
        'at': at,
        'stale': stale,
        'total': len(checks),
    }
