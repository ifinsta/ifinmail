"""Keep your mailing lists on the server: create one, load it from a CSV, see who can be mailed.
Needs a key with the marketing.send scope and the address it may send as.

    python 12_audiences.py new "Newsletter" example.com
    python 12_audiences.py import 7d2e... people.csv     # safe to run again after the list changes
    python 12_audiences.py show 7d2e...                  # how many people a campaign would reach
    python 12_audiences.py contacts 7d2e... --status opted_out
    python 12_audiences.py remove 7d2e... ana@example.org
    python 12_audiences.py delete 7d2e...
    python 12_audiences.py list

Then send to the whole list with ``11_marketing_campaign.py send ... --audience 7d2e...``.

``people.csv`` has an ``email`` column; every other column is a value for a ``{{merge}}`` tag,
as in ``11_marketing_campaign.py``. Importing adds new people, updates the values of the ones
already there and leaves the rest alone, so the CSV can be your export and you can load it on every
change. Whether a person can be mailed is not kept on the list: it is looked up, so someone who
unsubscribes from any campaign shows up as ``opted_out`` on every list of the domain at once.
"""

import argparse
import csv
from pathlib import Path

from ifinmail_client import Client, IfinmailError

HINTS = {
    403: 'The key lacks marketing.send, or does not send from that domain.',
    404: 'No such audience (or it belongs to another key).',
}


def read_people(path: Path) -> list[dict]:
    with path.open(newline='', encoding='utf-8') as handle:
        rows = list(csv.DictReader(handle))
    if not rows or 'email' not in rows[0]:
        raise SystemExit(f'{path} needs a header row with an "email" column.')
    people = []
    for row in rows:
        merge = {k.strip().lower(): v for k, v in row.items() if k and k != 'email' and v}
        people.append({'email': row['email'].strip(), 'merge': merge})
    return people


def show(audience: dict) -> None:
    counts = audience['contacts']
    print(f'{audience["id"]}  {audience["name"]}  ({audience["domain"]})')
    print(
        f'  {counts["total"]} people: {counts["reachable"]} reachable, '
        f'{counts["opted_out"]} opted out, {counts["suppressed"]} suppressed'
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest='command', required=True)
    new = commands.add_parser('new', help='create an audience')
    new.add_argument('name')
    new.add_argument('domain', help='the sending domain it is for')
    new.add_argument('--description', default='')
    load = commands.add_parser('import', help='add people from a CSV, or update them')
    load.add_argument('audience_id')
    load.add_argument('people', type=Path)
    commands.add_parser('list', help='your audiences')
    for name in ('show', 'delete'):
        commands.add_parser(name).add_argument('audience_id')
    contacts = commands.add_parser('contacts', help='the people on an audience')
    contacts.add_argument('audience_id')
    contacts.add_argument('--status', choices=['reachable', 'opted_out', 'suppressed'], default='')
    remove = commands.add_parser('remove', help='take one person off an audience')
    remove.add_argument('audience_id')
    remove.add_argument('email')
    args = parser.parse_args()

    api = Client.from_env()
    try:
        if args.command == 'new':
            made = api.create_audience(args.name, args.domain, args.description)
            print(f'created {made["id"]}')
        elif args.command == 'import':
            done = api.add_contacts(args.audience_id, read_people(args.people))
            print(', '.join(f'{n} {name}' for name, n in done.items() if n) or 'nothing to do')
        elif args.command == 'list':
            for audience in api.audiences():
                show(audience)
        elif args.command == 'show':
            show(api.audience(args.audience_id))
        elif args.command == 'contacts':
            for person in api.contacts(args.audience_id, status=args.status):
                print(f'{person["email"]}  {person["status"]}')
        elif args.command == 'remove':
            api.remove_contact(args.audience_id, args.email)
            print('removed')
        else:
            api.delete_audience(args.audience_id)
            print('deleted')
    except IfinmailError as exc:
        raise SystemExit(f'Failed. {HINTS.get(exc.status) or exc.detail}') from exc


if __name__ == '__main__':
    main()
