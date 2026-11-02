"""Audiences: lists of people a campaign can be sent to (Marketing plugin).

Until now a campaign carried its recipients in the request. An audience is a list kept on the
server: contacts with the values for the merge tags, imported in batches and changed over time,
which a campaign names instead of listing everyone again.

* An audience belongs to one **sending domain**. The opt-outs and the suppression list that decide
  who can be mailed are per domain, so each contact can be shown as reachable, opted out or
  suppressed, and a campaign cannot send one brand's list from another brand's address.
* **Whether someone can be mailed is not stored on the contact.** It is looked up when asked, from
  the same tables a campaign uses, so there is one source of truth: a person who unsubscribes
  from any campaign of the domain is opted out of every audience of the domain at once.
* A campaign takes a **snapshot** of the audience when it is created. Contacts added or removed
  afterwards do not change a campaign that exists.
* A key sees and changes the audiences it created; a key with ``mail.manage`` sees all of them.

Failures carry a status and a message that are safe to show.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q, QuerySet

from backend.apps.domains.models import Domain
from backend.apps.mail.models import Audience, Contact, MarketingOptOut, Suppression
from backend.apps.mail.services import marketing
from backend.apps.mail.services.messages import SendRefused, address

MAX_IMPORT_BATCH = 1000  # contacts in one import call
MAX_NAME = 120
MAX_DESCRIPTION = 300
MAX_SOURCE = 40

REACHABLE, OPTED_OUT, SUPPRESSED = 'reachable', 'opted_out', 'suppressed'
STATUSES = (REACHABLE, OPTED_OUT, SUPPRESSED)


@dataclass(frozen=True)
class AudienceKey:
    """What audiences need to know about the key making the call."""

    prefix: str
    domains: tuple[str, ...]  # the domains it may send from
    manager: bool = False  # mail.manage: sees every audience, on any hosted domain


@dataclass(frozen=True)
class ContactIn:
    email: str
    merge: dict | None = None  # None: keep what is there (or none, for a new contact)
    source: str = ''


@dataclass(frozen=True)
class ImportResult:
    added: int = 0
    updated: int = 0  # already there, with different values
    unchanged: int = 0  # already there, nothing to change
    invalid: int = 0  # not an address, or unusable merge values
    duplicate: int = 0  # named twice in the same request


def _require_enabled() -> marketing.MarketingSettings:
    cfg = marketing.settings()
    if not cfg.enabled:
        raise SendRefused(
            403, 'Marketing is switched off. Install or enable the Marketing plugin to use it.'
        )
    return cfg


# ------------------------------------------------------------------------------ audiences


def visible(key: AudienceKey) -> QuerySet[Audience]:
    rows = Audience.objects.all()
    return rows if key.manager else rows.filter(key_prefix=key.prefix)


def create(name: str, domain: str, description: str, key: AudienceKey) -> Audience:
    _require_enabled()
    clean_name = (name or '').strip()
    if not clean_name or len(clean_name) > MAX_NAME:
        raise SendRefused(422, f'Give the audience a name of 1 to {MAX_NAME} characters.')
    if len(description or '') > MAX_DESCRIPTION:
        raise SendRefused(422, f'The description is limited to {MAX_DESCRIPTION} characters.')
    wanted = (domain or '').strip().lower()
    if not Domain.objects.filter(name=wanted).exists():
        raise SendRefused(403, f'{wanted or "That"} is not a domain on this server.')
    if not key.manager and wanted not in key.domains:
        raise SendRefused(403, f'This key does not send from {wanted}.')
    return Audience.objects.create(
        name=clean_name,
        description=(description or '').strip(),
        domain=wanted,
        key_prefix=key.prefix,
    )


def rename(audience: Audience, name: str | None, description: str | None) -> Audience:
    if name is not None:
        clean = name.strip()
        if not clean or len(clean) > MAX_NAME:
            raise SendRefused(422, f'Give the audience a name of 1 to {MAX_NAME} characters.')
        audience.name = clean
    if description is not None:
        if len(description) > MAX_DESCRIPTION:
            raise SendRefused(422, f'The description is limited to {MAX_DESCRIPTION} characters.')
        audience.description = description.strip()
    audience.save(update_fields=['name', 'description'])
    return audience


# ------------------------------------------------------------------------------ who can be mailed


def _opted_out(domain_field: str) -> Exists:
    return Exists(
        MarketingOptOut.objects.filter(domain=OuterRef(domain_field), address=OuterRef('address'))
    )


def _suppressed(domain_field: str) -> Exists:
    return Exists(
        Suppression.objects.filter(domain=OuterRef(domain_field), address=OuterRef('address'))
    )


def status_of(opted: bool, gone: bool) -> str:
    """The same precedence a campaign uses when it skips someone: suppressed, then opted out."""
    if gone:
        return SUPPRESSED
    return OPTED_OUT if opted else REACHABLE


def contacts(audience: Audience, *, address: str = '', status: str = '') -> QuerySet[Contact]:
    """The audience's contacts, each annotated with ``opted`` and ``gone``; oldest first."""
    rows = audience.contacts.annotate(
        opted=_opted_out('audience__domain'), gone=_suppressed('audience__domain')
    )
    if address:
        rows = rows.filter(address=address.strip().lower())
    if status:
        if status not in STATUSES:
            raise SendRefused(422, f'status must be one of: {", ".join(STATUSES)}.')
        rows = {
            SUPPRESSED: rows.filter(gone=True),
            OPTED_OUT: rows.filter(gone=False, opted=True),
            REACHABLE: rows.filter(gone=False, opted=False),
        }[status]
    return rows


def counts_for(audiences: Iterable[Audience]) -> dict[object, dict[str, int]]:
    """``{pk: {total, reachable, opted_out, suppressed}}`` for many audiences, in one query."""
    found = {
        audience.pk: {'total': 0, REACHABLE: 0, OPTED_OUT: 0, SUPPRESSED: 0}
        for audience in audiences
    }
    rows = (
        Contact.objects.filter(audience_id__in=list(found))
        .values('audience_id')
        .order_by()
        .annotate(
            total=Count('pk'),
            suppressed=Count('pk', filter=Q(_suppressed('audience__domain'))),
            opted_out=Count(
                'pk', filter=Q(_opted_out('audience__domain')) & ~Q(_suppressed('audience__domain'))
            ),
        )
    )
    for row in rows:
        entry = found[row['audience_id']]
        entry['total'] = row['total']
        entry[SUPPRESSED] = row['suppressed']
        entry[OPTED_OUT] = row['opted_out']
        entry[REACHABLE] = row['total'] - row['suppressed'] - row['opted_out']
    return found


def counts(audience: Audience) -> dict[str, int]:
    return counts_for([audience])[audience.pk]


# ------------------------------------------------------------------------------ contacts


def import_contacts(audience: Audience, items: Sequence[ContactIn]) -> ImportResult:
    """Add contacts, or update the ones that are there (matched by address), in one batch.

    A contact given without ``merge`` keeps the values it has. Addresses and values that are not
    acceptable are counted as ``invalid`` and the rest go in. A batch that would take the audience
    over the plugin's size limit is refused whole, so a limit never cuts a list in two.
    """
    cfg = _require_enabled()
    if not items:
        raise SendRefused(422, 'Send at least one contact.')
    if len(items) > MAX_IMPORT_BATCH:
        raise SendRefused(
            422, f'At most {MAX_IMPORT_BATCH} contacts in one call; send the rest in more calls.'
        )
    tally: Counter[str] = Counter()
    wanted: dict[str, tuple[dict | None, str]] = {}
    for item in items:
        try:
            who = address(item.email)
        except SendRefused:
            tally['invalid'] += 1
            continue
        clean = marketing.clean_merge(item.merge) if item.merge is not None else None
        if item.merge is not None and clean is None:
            tally['invalid'] += 1
            continue
        if who in wanted:
            tally['duplicate'] += 1
            continue
        wanted[who] = (clean, (item.source or '').strip()[:MAX_SOURCE])

    with transaction.atomic():
        existing = {row.address: row for row in audience.contacts.filter(address__in=list(wanted))}
        new = [who for who in wanted if who not in existing]
        if new and audience.contacts.count() + len(new) > cfg.max_audience_size:
            raise SendRefused(
                422,
                f'This audience would have more than {cfg.max_audience_size} contacts, which is '
                'the most this server allows in one audience.',
            )
        Contact.objects.bulk_create(
            [
                Contact(
                    audience=audience,
                    address=who,
                    merge=wanted[who][0] or {},
                    source=wanted[who][1],
                )
                for who in new
            ],
            batch_size=500,
            ignore_conflicts=True,
        )
        changed: list[Contact] = []
        for who, row in existing.items():
            merge, source = wanted[who]
            if merge is not None and merge != row.merge:
                row.merge = merge
                if source:
                    row.source = source
                changed.append(row)
            else:
                tally['unchanged'] += 1
        if changed:
            Contact.objects.bulk_update(changed, ['merge', 'source'], batch_size=500)
    return ImportResult(
        added=len(new),
        updated=len(changed),
        unchanged=tally['unchanged'],
        invalid=tally['invalid'],
        duplicate=tally['duplicate'],
    )


def remove_contact(audience: Audience, email: str) -> bool:
    deleted, _ = audience.contacts.filter(address=(email or '').strip().lower()).delete()
    return bool(deleted)


def snapshot(audience: Audience) -> list[marketing.RecipientIn]:
    """Everyone on the audience as campaign recipients, as the list is now."""
    return [
        marketing.RecipientIn(address=who, merge=merge)
        for who, merge in audience.contacts.order_by('pk').values_list('address', 'merge')
    ]


__all__ = [
    'MAX_IMPORT_BATCH',
    'OPTED_OUT',
    'REACHABLE',
    'STATUSES',
    'SUPPRESSED',
    'AudienceKey',
    'ContactIn',
    'ImportResult',
    'contacts',
    'counts',
    'counts_for',
    'create',
    'import_contacts',
    'remove_contact',
    'rename',
    'snapshot',
    'status_of',
    'visible',
]
