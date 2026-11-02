"""Send a marketing campaign to a list: one email each, a personal unsubscribe link, paced.
Needs a key with the marketing.send scope and the address it may send as.

    python 11_marketing_campaign.py send news@example.com "Spring sale, {{first_name|friend}}" \
        body.txt people.csv --html body.html --name "Spring sale"
    python 11_marketing_campaign.py send news@example.com "Spring sale" body.txt --audience 7d2e...
    python 11_marketing_campaign.py status 1b0c...           # add --watch to follow it
    python 11_marketing_campaign.py pause 1b0c...            # also: resume, cancel

``people.csv`` has an ``email`` column; every other column is a value for a ``{{merge}}`` tag in
the subject or body (``{{first_name}}`` fills from a ``first_name`` column, and
``{{first_name|friend}}`` uses "friend" for anyone with no value). Nothing is sent by ``send``
itself: the server mails the list over time, at the pace its Marketing plugin allows, and the
answer says who was left out and why (unsubscribed, bounced before, blocked). The call is safe to
retry (an Idempotency-Key is sent for you), so a timeout never creates the campaign twice.

With ``--audience`` the campaign goes to everyone on a list kept on the server (see
``12_audiences.py``) instead of a CSV: the list is copied when the campaign is created.
"""

import argparse
import csv
from pathlib import Path

from ifinmail_client import Client, IfinmailError

HINTS = {
    403: 'The key lacks marketing.send, or may not send as that address.',
    409: 'Campaigns need the postal address set under Marketplace, Marketing.',
    422: 'The campaign was refused: ',
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


def show(state: dict) -> None:
    counts = state['recipients']
    line = ', '.join(f'{n} {name}' for name, n in counts.items() if n)
    rate = state.get('bounce_rate')
    print(f"{state['id']}  {state['status']}  {line}" + (f'  bounce rate {rate}%' if rate else ''))
    if state['status_detail']:
        print(f"  {state['status_detail']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest='command', required=True)
    send = commands.add_parser('send', help='create a campaign from a CSV of people')
    send.add_argument('sender')
    send.add_argument('subject')
    send.add_argument('text_file', type=Path, help='the plain-text body')
    send.add_argument('people', type=Path, nargs='?', help='a CSV with an email column')
    send.add_argument('--audience', help='send to this audience (its id) instead of a CSV')
    send.add_argument('--html', type=Path, help='an HTML version of the body')
    send.add_argument('--name', default='', help='your own label for the campaign')
    for name in ('status', 'pause', 'resume', 'cancel'):
        sub = commands.add_parser(name)
        sub.add_argument('campaign_id')
        if name == 'status':
            sub.add_argument('--watch', action='store_true', help='follow it until it ends')
    args = parser.parse_args()

    api = Client.from_env()
    try:
        if args.command == 'send':
            if bool(args.people) == bool(args.audience):
                raise SystemExit('Give a CSV of people, or --audience, but not both.')
            result = api.create_campaign(
                args.sender,
                args.subject,
                read_people(args.people) if args.people else None,
                audience=args.audience,
                text=args.text_file.read_text(encoding='utf-8'),
                html=args.html.read_text(encoding='utf-8') if args.html else None,
                name=args.name,
            )
            print(f"created {result['id']}: {result['queued']} to be sent")
            for reason, count in sorted(result['skipped'].items()):
                print(f'  left out: {count} {reason}')
        elif args.command == 'status':
            if args.watch:
                show(api.wait_for_campaign(args.campaign_id, every=15))
            else:
                show(api.campaign(args.campaign_id))
        else:
            actions = {
                'pause': api.pause_campaign,
                'resume': api.resume_campaign,
                'cancel': api.cancel_campaign,
            }
            show(actions[args.command](args.campaign_id))
    except IfinmailError as exc:
        hint = HINTS.get(exc.status, '')
        message = hint + exc.detail if exc.status == 422 else (hint or exc.detail)
        raise SystemExit(f'Failed. {message}') from exc


if __name__ == '__main__':
    main()
