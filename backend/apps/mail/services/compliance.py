"""Sender compliance: keep mail sent through the API inside the large providers' sender rules.

Gmail, Yahoo and Microsoft refuse or junk mail from senders who keep writing to addresses that do
not exist, ignore unsubscribes, or have no one-click unsubscribe on bulk mail. This plugin:

* keeps a **suppression list** per sending domain: recipients that bounced for good (added
  automatically from the delivery log), that unsubscribed, or that were added by hand or by an
  application. Suppressed recipients are removed from a message before it is sent (the answer
  lists them); a message left with no recipients is refused;
* adds **one-click unsubscribe** (RFC 8058) to mail marked as bulk (``"unsubscribe": true`` on
  ``POST /messages``) or to all API mail, as the plugin says: ``List-Unsubscribe`` with a signed
  https link and ``List-Unsubscribe-Post: List-Unsubscribe=One-Click``. The link's page asks for
  a click, so a link scanner opening it unsubscribes no one; the mail provider's one-click POST
  unsubscribes at once;
* **pauses a key** whose bounce rate over the day passes the limit (with at least 50 messages),
  until an administrator resumes it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.core import signing
from django.core.cache import cache
from django.db import IntegrityError

from backend.apps.core.plugins.services import InstallationService
from backend.apps.mail.models import Suppression

logger = logging.getLogger('backend')

CAPABILITY = 'developer.compliance'
_SALT = 'ifinmail.unsubscribe.v1'
_GUARD_MIN_MESSAGES = 50
_HARD_CATEGORIES = {'unknown_recipient'}  # the address does not exist: it never will by retrying


class ComplianceError(ValueError):
    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class ComplianceSettings:
    enabled: bool
    unsubscribe: str  # off | bulk | all
    bounce_limit: int  # percent; 0: no guard
    suppress_bounces: bool


def settings() -> ComplianceSettings:
    values = InstallationService.capability_values(CAPABILITY)
    try:
        limit = int(values.get('bounce_limit') or 0)
    except ValueError:
        limit = 0
    return ComplianceSettings(
        enabled=values.get('enabled') == 'yes',
        unsubscribe=values.get('unsubscribe') or 'bulk',
        bounce_limit=limit,
        suppress_bounces=values.get('suppress_bounces', 'yes') == 'yes',
    )


# ------------------------------------------------------------------------------ suppressions


def _domain_of(sender: str) -> str:
    return sender.rpartition('@')[2].lower()


def suppressed(sender: str, recipients: list[str]) -> list[str]:
    domain = _domain_of(sender)
    found = set(
        Suppression.objects.filter(domain=domain, address__in=[r.lower() for r in recipients])
        .values_list('address', flat=True)
    )
    return [r for r in recipients if r.lower() in found]


def suppress(domain: str, address: str, reason: str, *, detail: str = '', by: str = '') -> bool:
    """Add one; returns False when it was already there."""
    try:
        Suppression.objects.create(
            domain=domain.lower(),
            address=address.strip().lower(),
            reason=reason,
            detail=detail[:300],
            created_by=by[:255],
        )
    except IntegrityError:
        return False
    return True


def unsuppress(domain: str, address: str) -> int:
    deleted, _ = Suppression.objects.filter(domain=domain.lower(), address=address.strip().lower()).delete()
    return deleted


def listing(domains: list[str] | None, *, address: str = '') -> list[Suppression]:
    rows = Suppression.objects.all()
    if domains is not None:
        rows = rows.filter(domain__in=[d.lower() for d in domains])
    if address:
        rows = rows.filter(address=address.strip().lower())
    return list(rows[:1000])


def note_bounce(sender: str, recipient: str, category: str, dsn: str, reason: str) -> None:
    """From the delivery log: a permanent failure for a reason that will not change."""
    current = settings()
    if not current.enabled or not current.suppress_bounces:
        return
    if not dsn.startswith('5') or category not in _HARD_CATEGORIES:
        return
    if suppress(_domain_of(sender), recipient, Suppression.BOUNCED, detail=f'{dsn} {reason}'[:300]):
        logger.info('Suppressed %s for %s after a permanent bounce', recipient, _domain_of(sender))


# ------------------------------------------------------------------------------ one click


def unsubscribe_token(sender: str, recipient: str) -> str:
    return signing.dumps({'d': _domain_of(sender), 'r': recipient.lower()}, salt=_SALT, compress=True)


def read_token(token: str) -> tuple[str, str] | None:
    try:
        data = signing.loads(token, salt=_SALT, max_age=400 * 24 * 3600)
    except signing.BadSignature:
        return None
    return str(data.get('d', '')), str(data.get('r', ''))


def unsubscribe_headers(sender: str, recipient: str, *, bulk: bool) -> dict[str, str]:
    """RFC 8058 headers for one recipient, or ``{}`` when the plugin does not add them."""
    current = settings()
    if not current.enabled or current.unsubscribe == 'off':
        return {}
    if current.unsubscribe == 'bulk' and not bulk:
        return {}
    from backend.config import site_url

    url = site_url.absolute_url(None, 'unsubscribe', unsubscribe_token(sender, recipient))
    return {'List-Unsubscribe': f'<{url}>', 'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click'}


# ------------------------------------------------------------------------------ bounce guard


def _counter(prefix: str, kind: str) -> str:
    return f'compliance:{prefix}:{kind}'


def count(prefix: str, *, delivered: int = 0, bounced: int = 0) -> None:
    for kind, amount in (('ok', delivered), ('bounced', bounced)):
        if amount:
            try:
                cache.add(_counter(prefix, kind), 0, 24 * 3600)
                cache.incr(_counter(prefix, kind), amount)
            except Exception:
                logger.warning('Compliance counters unavailable')
    _check_guard(prefix)


def bounce_rate(prefix: str) -> tuple[float | None, int]:
    try:
        ok = int(cache.get(_counter(prefix, 'ok')) or 0)
        bad = int(cache.get(_counter(prefix, 'bounced')) or 0)
    except Exception:
        return None, 0
    total = ok + bad
    return (round(100 * bad / total, 1) if total else None), total


def _check_guard(prefix: str) -> None:
    current = settings()
    if not current.enabled or not current.bounce_limit:
        return
    rate, total = bounce_rate(prefix)
    if rate is not None and total >= _GUARD_MIN_MESSAGES and rate > current.bounce_limit:
        if cache.add(f'compliance:paused:{prefix}', {'rate': rate, 'total': total}, None):
            from backend.apps.core.platform.services.audit import AuditService

            AuditService.record(
                action='api_key_paused_for_bounces',
                user='compliance',
                detail=f'ifm_{prefix}: {rate}% of {total} messages bounced',
            )


def paused(prefix: str) -> dict | None:
    try:
        found = cache.get(f'compliance:paused:{prefix}')
    except Exception:
        return None
    return found if isinstance(found, dict) else None


def resume(prefix: str) -> None:
    for key in (f'compliance:paused:{prefix}', _counter(prefix, 'ok'), _counter(prefix, 'bounced')):
        try:
            cache.delete(key)
        except Exception:
            pass
