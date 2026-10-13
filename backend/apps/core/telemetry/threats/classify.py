"""What a request path or user agent says about the person sending it.

Scanners ask for the same few hundred files. Naming the *class* of a probe (a dotenv file, a
version-control directory, a WordPress admin) is enough to decide, and it is also all the model
ever needs to be told: the path itself is attacker-controlled text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Patterns are anchored on path segments and avoid nested quantifiers, so a hostile path cannot
# make a match slow.
_FLAGS = re.IGNORECASE


@dataclass(frozen=True)
class ProbeClass:
    name: str
    pattern: re.Pattern[str]
    sensitive: bool  # a 2xx here means something that should be private was served


def _c(name: str, pattern: str, *, sensitive: bool = False) -> ProbeClass:
    return ProbeClass(name, re.compile(pattern, _FLAGS), sensitive)


PROBE_CLASSES: tuple[ProbeClass, ...] = (
    _c('dotenv', r'(?:^|/)\.env(?:[./_-]|$)', sensitive=True),
    _c('vcs', r'/\.(?:git|svn|hg|bzr)(?:/|$)', sensitive=True),
    _c(
        'secrets',
        r'(?:^|/)(?:\.aws|\.ssh|\.docker|\.npmrc|\.htpasswd|\.pgpass|id_rsa|wp-config\.php|'
        r'credentials(?:\.json)?|secrets?\.(?:json|ya?ml))(?:/|$)',
        sensitive=True,
    ),
    _c(
        'backup',
        r'\.(?:bak|backup|old|orig|save|sql|dump|zip|tar|tgz|gz|7z|rar)$',
        sensitive=True,
    ),
    _c('wordpress', r'/(?:wp-(?:admin|login|content|includes|json)|xmlrpc\.php)'),
    _c('php_admin', r'/(?:phpmyadmin|pma|adminer|phpinfo|info\.php)'),
    _c(
        'framework',
        r'/(?:actuator|vendor/phpunit|_profiler|telescope|debug/default|server-status|'
        r'console/?$|jenkins|solr|manager/html|owa/|ecp/)',
    ),
    _c('cgi_shell', r'/(?:cgi-bin|boaform|HNAP1|GponForm|setup\.cgi|eval-stdin\.php|shell|cmd)'),
    _c('traversal', r'(?:\.\./|%2e%2e|%252e|/etc/passwd)'),
    _c('injection', r'(?:<script|%3cscript|union(?:\s|%20|\+)+select|\$\{jndi|\bor(?:\s|\+)1=1)'),
)

_SCANNER_AGENTS = (
    'zgrab',
    'masscan',
    'nuclei',
    'nikto',
    'sqlmap',
    'wpscan',
    'dirbuster',
    'gobuster',
    'nmap',
    'censys',
    'leakix',
    'netcraft',
    'httpx',
    'fuzz faster',
)
_UNPRINTABLE = re.compile(r'[^\x20-\x7e]')


def probe_class(path: str, query: str = '') -> ProbeClass | None:
    """The first probe class that matches, or None for an ordinary request."""
    target = f'{path}?{query}' if query else path
    for candidate in PROBE_CLASSES:
        if candidate.pattern.search(target):
            return candidate
    return None


def is_raw_protocol(method: str, path: str) -> bool:
    """TLS or another binary protocol sent to an HTTP port (nginx logs it as a request)."""
    return not method.isalpha() or (path[:1] != '/' and path != '*')


def is_scanner_agent(user_agent: str) -> bool:
    lowered = user_agent.lower()
    return any(name in lowered for name in _SCANNER_AGENTS)


def clean(text: str, limit: int = 80) -> str:
    """Printable ASCII only, bounded: safe to store, to show, and to hand to a model as data."""
    return _UNPRINTABLE.sub('?', text)[:limit]
