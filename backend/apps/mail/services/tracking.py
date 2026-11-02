"""Open and click tracking for campaigns, and the report built from it (Marketing plugin).

* **Opens.** The html part of each email ends with a one-pixel image whose address is personal to
  the person. Fetching it counts an open.
* **Clicks.** Each ``http(s)`` link in the html goes to this server first, which counts the click
  and sends the person on to the real address. The real addresses are kept with the campaign
  (``CampaignLink``); a tracked address carries only the numbers of the person and the link, signed,
  so it cannot be made to redirect anywhere else.

What this can and cannot tell you, because the numbers are easy to over-read:

* An open is a pixel being fetched. A mail app that loads images in advance for privacy (Apple Mail
  Privacy Protection) fetches it whether or not anybody read the email, so opens are an upper
  bound, and a person who blocks images is never counted. Clicks are the stronger signal.
* Some security scanners open every link in a message the moment it arrives. Requests that identify
  as a bot or a scanner, and ``HEAD`` requests, are sent on but not counted; a scanner that looks
  like a browser cannot be told apart.
* Only the html part is tracked. A link in the plain-text part is not counted, and a text-only
  campaign has no tracking at all.

The counts are kept as numbers on the recipient and the link, and one row per person per link
clicked, so the cost of tracking is bounded by people times links and not by how often a
mail app fetches an image.
"""

from __future__ import annotations

import html as html_lib
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote, urlsplit

from django.db import IntegrityError, transaction
from django.db.models import Count, F, Sum
from django.db.models.functions import TruncDay, TruncHour
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from backend.apps.mail.models import Campaign, CampaignClick, CampaignLink, CampaignRecipient

MAX_LINKS = 100  # tracked links per campaign; further ones are left as written
MAX_URL = 2000
MAX_BUCKETS = 500  # points returned in a report's timeline

_SALT = 'ifinmail.marketing.tracking.v1'
_SIGNATURE_LENGTH = 20

# <a ... href="...">  or  href='...'  (the value is what is rewritten)
_HREF = re.compile(r"""(<a\b[^>]*?\shref\s*=\s*)(?:"([^"]*)"|'([^']*)')""", re.I | re.S)

# Fetchers that are not a person: counted as nothing, still sent on.
_MACHINES = (
    'bot',
    'crawler',
    'spider',
    'scanner',
    'preview',
    'headless',
    'curl/',
    'wget',
    'python-requests',
    'go-http-client',
    'java/',
    'safelinks',
    'barracuda',
    'proofpoint',
    'mimecast',
)

# A transparent 1x1 GIF.
PIXEL = bytes.fromhex(
    '47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b'
)


# ------------------------------------------------------------------------------ tokens


def _sign(*parts: object) -> str:
    message = '.'.join(str(part) for part in parts)
    return salted_hmac(_SALT, message, algorithm='sha256').hexdigest()[:_SIGNATURE_LENGTH]


def open_token(recipient_id: int) -> str:
    return f'{recipient_id}.{_sign("o", recipient_id)}'


def click_token(recipient_id: int, link_id: int) -> str:
    return f'{recipient_id}.{link_id}.{_sign("c", recipient_id, link_id)}'


def read_open_token(token: str) -> int | None:
    recipient, _, signature = token.partition('.')
    if not recipient.isdigit() or not constant_time_compare(signature, _sign('o', int(recipient))):
        return None
    return int(recipient)


def read_click_token(token: str) -> tuple[int, int] | None:
    recipient, _, rest = token.partition('.')
    link, _, signature = rest.partition('.')
    if not (recipient.isdigit() and link.isdigit()):
        return None
    if not constant_time_compare(signature, _sign('c', int(recipient), int(link))):
        return None
    return int(recipient), int(link)


def open_url(recipient_id: int) -> str:
    from backend.config import site_url

    return site_url.absolute_url(None, 'marketing_open', open_token(recipient_id))


def click_url(recipient_id: int, link_id: int) -> str:
    from backend.config import site_url

    return site_url.absolute_url(None, 'marketing_click', click_token(recipient_id, link_id))


# ------------------------------------------------------------------------------ what is tracked


def trackable(url: str) -> bool:
    """A link worth counting: a web address, not a mailto, an anchor or a merge tag alone."""
    return url.startswith(('http://', 'https://')) and len(url) <= MAX_URL


def _hrefs(html: str) -> Iterable[tuple[re.Match[str], str]]:
    for match in _HREF.finditer(html or ''):
        raw = match.group(2) if match.group(2) is not None else match.group(3)
        yield match, html_lib.unescape(raw).strip()


def links_in(html: str) -> list[str]:
    """The distinct tracked addresses in the html, in order of appearance (up to ``MAX_LINKS``)."""
    found: list[str] = []
    for _, url in _hrefs(html):
        if trackable(url) and url not in found:
            found.append(url)
            if len(found) >= MAX_LINKS:
                break
    return found


def create_links(campaign: Campaign) -> int:
    """Record the links of a campaign's html; call once, when the campaign is created."""
    urls = links_in(campaign.html) if campaign.track_clicks else []
    CampaignLink.objects.bulk_create(
        [CampaignLink(campaign=campaign, url=url, position=i) for i, url in enumerate(urls)]
    )
    return len(urls)


def link_ids(campaign: Campaign) -> dict[str, int]:
    """``{address: link id}`` for the campaign, to look up while composing its emails."""
    return dict(CampaignLink.objects.filter(campaign=campaign).values_list('url', 'pk'))


@dataclass(frozen=True)
class Tracking:
    """What composing one person's email needs to add tracking to it."""

    recipient_id: int
    opens: bool
    links: Mapping[str, int] | None  # None: do not count clicks


def rewrite_links(html: str, recipient_id: int, links: Mapping[str, int]) -> str:
    """Point the tracked links at this server. Run on the message as written, before merging."""
    if not links:
        return html

    def swap(match: re.Match[str]) -> str:
        raw = match.group(2) if match.group(2) is not None else match.group(3)
        link = links.get(html_lib.unescape(raw).strip())
        if link is None:
            return match.group(0)
        return f'{match.group(1)}"{html_lib.escape(click_url(recipient_id, link), quote=True)}"'

    return _HREF.sub(swap, html)


def pixel_html(recipient_id: int) -> str:
    return (
        f'<img src="{html_lib.escape(open_url(recipient_id), quote=True)}" width="1" height="1" '
        'alt="" style="display:none;border:0;width:1px;height:1px" />'
    )


# ------------------------------------------------------------------------------ recording


def is_machine(user_agent: str) -> bool:
    agent = (user_agent or '').lower()
    return any(marker in agent for marker in _MACHINES)


def record_open(recipient_id: int, *, counted: bool = True, now: datetime | None = None) -> bool:
    """Count an open. Returns False when there is no such recipient."""
    now = now or timezone.now()
    found = CampaignRecipient.objects.filter(pk=recipient_id, campaign__track_opens=True)
    if not found.exists():
        return False
    if counted:
        found.update(opens=F('opens') + 1)
        found.filter(first_opened_at__isnull=True).update(first_opened_at=now)
    return True


def record_click(
    recipient_id: int, link_id: int, *, counted: bool = True, now: datetime | None = None
) -> CampaignLink | None:
    """Count a click and return the link, or ``None`` when the person or link is gone."""
    now = now or timezone.now()
    link = CampaignLink.objects.filter(
        pk=link_id, campaign__recipients__pk=recipient_id, campaign__track_clicks=True
    ).first()
    if link is None:
        return None
    if not counted:
        return link
    try:
        with transaction.atomic():
            row, created = CampaignClick.objects.get_or_create(recipient_id=recipient_id, link=link)
    except IntegrityError:  # two clicks at once: the other one made the row
        row, created = CampaignClick.objects.get(recipient_id=recipient_id, link=link), False
    if not created:
        CampaignClick.objects.filter(pk=row.pk).update(count=F('count') + 1)
    CampaignLink.objects.filter(pk=link.pk).update(
        clicks=F('clicks') + 1, unique_clicks=F('unique_clicks') + (1 if created else 0)
    )
    people = CampaignRecipient.objects.filter(pk=recipient_id)
    people.update(clicks=F('clicks') + 1)
    people.filter(first_clicked_at__isnull=True).update(first_clicked_at=now)
    return link


def destination(link: CampaignLink, recipient_id: int) -> str | None:
    """Where a click goes: the link with this person's own values filled into its merge tags.

    Values are percent-encoded, so one cannot change the address it is part of. The result must
    still be a web address, or there is no destination.
    """
    from backend.apps.mail.services import marketing

    url = link.url
    if '{{' in url:
        person = CampaignRecipient.objects.filter(pk=recipient_id).first()
        if person is None:
            return None
        values = {
            **{k: v for k, v in (person.merge or {}).items() if isinstance(v, str)},
            'email': person.address,
        }
        url = marketing.render(
            url, {k: quote(v, safe='') for k, v in values.items()}, escape=False, missing=[]
        )
    parts = urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.netloc or '{{' in url:
        return None
    return url


# ------------------------------------------------------------------------------ the report


def _percent(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def report(campaign: Campaign, *, by: str = 'hour') -> dict[str, object]:
    """Opens, clicks, links and a timeline for one campaign."""
    people = CampaignRecipient.objects.filter(campaign=campaign)
    sent = people.filter(status=CampaignRecipient.SENT).count()
    opened = people.filter(first_opened_at__isnull=False).aggregate(
        people=Count('pk'), total=Sum('opens')
    )
    clicked = people.filter(first_clicked_at__isnull=False).aggregate(
        people=Count('pk'), total=Sum('clicks')
    )
    unique_opens, unique_clicks = opened['people'] or 0, clicked['people'] or 0

    truncate = TruncDay if by == 'day' else TruncHour
    timeline: dict[datetime, dict[str, int]] = {}
    for field, name in (('first_opened_at', 'opens'), ('first_clicked_at', 'clicks')):
        rows = (
            people.filter(**{f'{field}__isnull': False})
            .annotate(bucket=truncate(field))
            .values('bucket')
            .order_by('bucket')
            .annotate(n=Count('pk'))
        )
        for row in rows:
            timeline.setdefault(row['bucket'], {'opens': 0, 'clicks': 0})[name] = row['n']
    points = [{'at': at.isoformat(timespec='seconds'), **timeline[at]} for at in sorted(timeline)][
        -MAX_BUCKETS:
    ]

    return {
        'sent': sent,
        'tracking': {'opens': campaign.track_opens, 'clicks': campaign.track_clicks},
        'opens': {
            'people': unique_opens,
            'total': opened['total'] or 0,
            'rate': _percent(unique_opens, sent),
        },
        'clicks': {
            'people': unique_clicks,
            'total': clicked['total'] or 0,
            'rate': _percent(unique_clicks, sent),
            # Of the people who opened, how many clicked. Not meaningful when opens are not counted.
            'of_openers': _percent(
                people.filter(
                    first_opened_at__isnull=False, first_clicked_at__isnull=False
                ).count(),
                unique_opens,
            ),
        },
        'links': [
            {'url': link.url, 'clicks': link.clicks, 'people': link.unique_clicks}
            for link in campaign.links.all()
        ],
        'timeline': points,
    }


__all__ = [
    'MAX_LINKS',
    'PIXEL',
    'Tracking',
    'click_token',
    'click_url',
    'create_links',
    'destination',
    'is_machine',
    'link_ids',
    'links_in',
    'open_token',
    'open_url',
    'pixel_html',
    'read_click_token',
    'read_open_token',
    'record_click',
    'record_open',
    'report',
    'rewrite_links',
    'trackable',
]
