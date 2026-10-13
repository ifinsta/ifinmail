"""The adaptive part of the digest: learn what is normal on this server, flag what is not.

Three things adapt, all from data the server already keeps and none of it message content:

* **Places.** Where each account signs in from (country and network operator, never more than the
  /24). Once an account has an established history, a sign-in from somewhere it has never used is a
  finding: a stolen password is usually used from somewhere new. Nothing is learned until location
  data is installed, so that the baseline does not change meaning when it arrives.
* **Traffic.** The hourly digests already kept are the baseline: this hour of the day, compared
  with the same hour on earlier days, using the median and its spread, so one bad day does not
  teach the server that attacks are normal.
* **Campaigns.** Networks with findings that belong to one operator are one actor, not many.

Everything here only *raises findings*; it never changes a limit or a block by itself (that stays
with the opt-in Automatic protection). ``THREAT_ADAPTIVE=0`` turns it off.
"""

from __future__ import annotations

import os
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from backend.apps.core.telemetry.models import KnownPlace, ThreatDigest

from . import geo
from .rules import _SESSIONS, NETWORK_KINDS, is_internal
from .types import Access, Action, AuthEvent, Finding, MailEvent, Severity, WindowSummary

MIN_SIGNINS = 5  # an account is "established" after this many recorded sign-ins ...
MIN_AGE = timedelta(days=2)  # ... spread over at least this long
KEEP_PLACES = timedelta(days=180)
HISTORY_DAYS = 14
MIN_SAMPLES = 5  # same-hour digests needed before a traffic baseline means anything
CAMPAIGN_NETWORKS = 3
MAX_PLACE_FINDINGS = 20
SURGE_FLOORS = {'requests': 300, 'auth_failures': 15, 'mail_failures': 15}
SURGE_NAMES = {
    'requests': 'web requests',
    'auth_failures': 'failed console sign-ins',
    'mail_failures': 'failed mail sign-ins',
}


def enabled() -> bool:
    return os.environ.get('THREAT_ADAPTIVE', '1').lower() not in ('0', 'false', 'no')


@dataclass(frozen=True)
class SignIn:
    at: datetime
    actor: str
    channel: str  # console | mail
    net: str


def sign_ins(auth: list[AuthEvent], mail: list[MailEvent]) -> list[SignIn]:
    found = [
        SignIn(e.at, e.who.lower(), 'console', e.net)
        for e in auth
        if e.kind == 'login_success' and e.net and '@' in e.who
    ]
    found += [
        SignIn(e.at, e.who.lower(), 'mail', e.net)
        for e in mail
        if e.kind == 'login_success' and e.net and '@' in e.who
    ]
    found.sort(key=lambda s: s.at)
    return found


# -- places ------------------------------------------------------------------------------------


def _established(actor: str, now: datetime) -> bool:
    rows = list(KnownPlace.objects.filter(actor=actor).values_list('count', 'first_seen'))
    if not rows:
        return False
    return bool(sum(c for c, _ in rows) >= MIN_SIGNINS and min(f for _, f in rows) <= now - MIN_AGE)


def learn_places(events: list[SignIn], now: datetime, reader: geo.Reader) -> list[Finding]:
    """Record where accounts sign in from; a first sighting is a finding once history exists."""
    findings: list[Finding] = []
    established: dict[str, bool] = {}
    for event in events:
        place = reader.lookup_net(event.net)
        if not place.known:
            continue  # an unlocated network says nothing about "somewhere new"
        established.setdefault(event.actor, _established(event.actor, now))
        existing = list(KnownPlace.objects.filter(actor=event.actor, place=place.key))
        mine = next((r for r in existing if r.channel == event.channel), None)
        if mine is not None:
            if event.at > mine.last_seen:
                mine.days += int(event.at.date() != mine.last_seen.date())
                mine.count += 1
                mine.last_seen = event.at
                mine.net = event.net
                mine.save(update_fields=['days', 'count', 'last_seen', 'net', 'updated_at'])
            continue
        others = KnownPlace.objects.filter(actor=event.actor)
        countries = {r.country for r in others if r.country}
        KnownPlace.objects.create(
            actor=event.actor,
            channel=event.channel,
            place=place.key,
            country=place.country,
            asn=place.asn,
            org=place.org[:120],
            net=event.net,
            first_seen=event.at,
            last_seen=event.at,
        )
        if existing or not established[event.actor] or len(findings) >= MAX_PLACE_FINDINGS:
            continue  # used before (on another channel), still learning, or enough already
        usual = [
            f'{r.country or "??"} AS{r.asn}' + (f' {r.org}' if r.org else '')
            for r in others.order_by('-count')[:3]
        ]
        new_country = bool(place.country and countries and place.country not in countries)
        via = 'the console' if event.channel == 'console' else 'the mail ports'
        findings.append(
            Finding(
                key=f'new_place:{event.actor}:{place.key}',
                kind='new_place',
                severity=Severity.MEDIUM if new_country else Severity.LOW,
                subject=event.actor,
                title=(
                    'Sign-in from a country this account has not used before'
                    if new_country
                    else 'Sign-in from a place this account has not used before'
                ),
                summary=(
                    f'{event.actor} signed in to {via} from {place.text()} for the first time '
                    f'(network {event.net}). Usually: {"; ".join(usual) or "no other place"}. '
                    'A password that was guessed or stolen is usually first used somewhere new.'
                ),
                count=1,
                first_seen=event.at,
                last_seen=event.at,
                samples=[place.text()],
                tighten=[_SESSIONS],
            )
        )
    return findings


# -- traffic -----------------------------------------------------------------------------------


def surges(summary: WindowSummary, now: datetime) -> list[Finding]:
    """This hour of the day compared with the same hour on earlier days."""
    start = now.replace(minute=0, second=0, microsecond=0)
    history = ThreatDigest.objects.filter(
        hour__gte=start - timedelta(days=HISTORY_DAYS), hour__lt=start
    ).values_list('hour', 'summary')
    same = [s for h, s in history if h.hour == start.hour and isinstance(s, dict)]
    if len(same) < MIN_SAMPLES:
        return []
    found: list[Finding] = []
    for metric, floor in SURGE_FLOORS.items():
        now_value = int(getattr(summary, metric, 0) or 0)
        values = [int(s.get(metric, 0) or 0) for s in same]
        median = statistics.median(values)
        spread = statistics.median(abs(v - median) for v in values)
        limit = median + max(4 * spread, 2 * median, floor)
        if now_value < max(limit, floor):
            continue
        found.append(
            Finding(
                key=f'surge:{metric}',
                kind='traffic_surge',
                severity=Severity.HIGH if now_value >= 3 * limit else Severity.MEDIUM,
                subject=SURGE_NAMES[metric],
                title='Traffic far above what is normal for this hour',
                summary=(
                    f'{now_value:,} {SURGE_NAMES[metric]} in the last hour. This hour of the day '
                    f'usually sees about {int(median):,} (up to {int(limit):,}), going by the '
                    f'last {len(same)} days.'
                ),
                count=now_value,
                first_seen=summary.start,
                last_seen=summary.end,
                tighten=[
                    Action(
                        'Look at the findings below',
                        '',
                        'A surge spread over many networks shows up here before any one network '
                        'crosses a threshold.',
                    )
                ],
            )
        )
    return found


# -- campaigns and where traffic comes from ----------------------------------------------------


def campaigns(findings: list[Finding], reader: geo.Reader) -> list[Finding]:
    """Findings about several networks of one operator at once: one actor, many addresses."""
    by_operator: dict[int, list[Finding]] = defaultdict(list)
    places: dict[int, geo.Place] = {}
    for finding in findings:
        if finding.kind not in NETWORK_KINDS or is_internal(finding.subject):
            continue
        place = reader.lookup_net(finding.subject)
        if place.asn:
            by_operator[place.asn].append(finding)
            places[place.asn] = place
    found: list[Finding] = []
    for asn, items in by_operator.items():
        nets = sorted({f.subject for f in items})
        if len(nets) < CAMPAIGN_NETWORKS:
            continue
        place = places[asn]
        kinds = sorted({f.kind.replace('_', ' ') for f in items})
        found.append(
            Finding(
                key=f'campaign:AS{asn}',
                kind='campaign',
                severity=max(f.severity for f in items),
                subject=f'AS{asn} {place.org}'[:190],
                title='Several networks of one operator are attacking at once',
                summary=(
                    f'{len(nets)} networks of {place.org or f"AS{asn}"} ({place.text()}) have '
                    f'findings in the last hour ({", ".join(kinds)}). That is one actor using '
                    'many addresses, so blocking them together is more useful than one at a time.'
                ),
                count=sum(f.count for f in items),
                first_seen=min(f.first_seen for f in items),
                last_seen=max(f.last_seen for f in items),
                samples=nets[:10],
                tighten=[
                    Action(
                        'Block these networks',
                        'network',
                        'Block them together from this finding, or one by one below.',
                    )
                ],
            )
        )
    return found


def where_from(
    requests: list[Access], mail: list[MailEvent], reader: geo.Reader
) -> tuple[dict[str, int], list[dict[str, object]]]:
    """Events by country and by operator: aggregates only, for the page and the assistant."""
    per_net: Counter[str] = Counter()
    for request in requests:
        per_net[request.net] += 1
    for event in mail:
        if event.kind in ('auth_failed', 'relay_denied', 'unknown_recipient'):
            per_net[event.net] += event.weight
    countries: Counter[str] = Counter()
    operators: dict[int, dict[str, object]] = {}
    for net, count in per_net.items():
        if is_internal(net):
            continue
        place = reader.lookup_net(net)
        countries[place.country or '??'] += count
        if place.asn:
            row = operators.setdefault(
                place.asn,
                {
                    'asn': place.asn,
                    'org': place.org,
                    'country': place.country,
                    'events': 0,
                    'networks': 0,
                },
            )
            row['events'] = int(row['events']) + count  # type: ignore[call-overload]
            row['networks'] = int(row['networks']) + 1  # type: ignore[call-overload]
    top = sorted(operators.values(), key=lambda r: -int(r['events']))[:6]  # type: ignore[call-overload]
    return dict(countries.most_common(10)), top


def run(
    requests: list[Access],
    auth_window: list[AuthEvent],
    mail: list[MailEvent],
    findings: list[Finding],
    summary: WindowSummary,
    now: datetime,
) -> list[Finding]:
    """Adaptive findings for this pass; also fills ``summary.countries`` and ``providers``."""
    if not enabled():
        return []
    extra = surges(summary, now)
    reader = geo.reader()
    if reader is None:
        return extra
    with reader:
        summary.countries, summary.providers = where_from(requests, mail, reader)
        extra += campaigns(findings, reader)
        extra += learn_places(sign_ins(auth_window, mail), now, reader)
    return extra


def forget(now: datetime) -> int:
    """Retention: places not seen for a long time, and those of accounts that no longer exist."""
    from backend.apps.accounts.models import MailUser

    old, _ = KnownPlace.objects.filter(last_seen__lt=now - KEEP_PLACES).delete()
    live = {e.lower() for e in MailUser.objects.values_list('email', flat=True)}
    stale = [
        a for a in KnownPlace.objects.values_list('actor', flat=True).distinct() if a not in live
    ]
    gone, _ = KnownPlace.objects.filter(actor__in=stale).delete() if stale else (0, {})
    return old + gone


def status() -> dict[str, object]:
    """What the page says about learning: how much is known, and whether location data is there."""
    places = KnownPlace.objects.count()
    return {
        'enabled': enabled(),
        'places': places,
        'accounts': KnownPlace.objects.values('actor').distinct().count() if places else 0,
        'geo': geo.info(),
        'attribution': geo.ATTRIBUTION,
    }
