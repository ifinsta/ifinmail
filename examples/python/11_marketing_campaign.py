"""Send a marketing campaign to a list: one email each, a personal unsubscribe link, paced.
Needs a key with the marketing.send scope and the address it may send as.

    python 11_marketing_campaign.py send news@example.com "Spring sale, {{first_name|friend}}" \
        body.txt people.csv --html body.html --name "Spring sale"
    python 11_marketing_campaign.py send news@example.com "Spring sale" body.txt --audience 7d2e...
    python 11_marketing_campaign.py from-template news@example.com 4c1a... --audience 7d2e...
    python 11_marketing_campaign.py send ... --send-at 2026-03-01T09:00:00+01:00   # schedule it
    python 11_marketing_campaign.py status 1b0c...           # add --watch to follow it
    python 11_marketing_campaign.py pause 1b0c...            # also: resume, cancel, start
    python 11_marketing_campaign.py reschedule 1b0c... 2026-03-02T09:00:00+01:00
    python 11_marketing_campaign.py report 1b0c...           # opens, clicks, each link

``people.csv`` has an ``email`` column; every other column is a value for a ``{{merge}}`` tag in
the subject or body (``{{first_name}}`` fills from a ``first_name`` column, and
``{{first_name|friend}}`` uses "friend" for anyone with no value). Nothing is sent by ``send``
itself: the server mails the list over time, at the pace its Marketing plugin allows, and the
answer says who was left out and why (unsubscribed, bounced before, blocked). The call is safe to
retry (an Idempotency-Key is sent for you), so a timeout never creates the campaign twice.

With ``--audience`` the campaign goes to everyone on a list kept on the server (see
``12_audiences.py``) instead of a CSV: the list is copied when the campaign is created.
``from-template`` starts from a message kept on the server (see ``13_templates.py``); a
``--subject`` or ``--text-file`` you give wins over the template's.

``--send-at`` (a time with a zone) schedules the campaign: it is created now and starts then. A
scheduled campaign can be moved (``reschedule``), started early (``start``) or cancelled.

Opens and clicks are counted by default (``--no-opens`` / ``--no-clicks`` turn them off for one
campaign). Read ``report`` with care: an open is a tracking image being fetched, and mail apps that
load images in advance make opens look higher than they are; clicks are the stronger signal. Only
the html part is tracked.
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


def show_report(report: dict) -> None:
    opens, clicks = report['opens'], report['clicks']
    print(
        f'sent {report["sent"]}, failed {report["failed"]}, skipped {report["skipped"]}, '
        f'bounced {report["bounced"]}'
    )
    if not (report['tracking']['opens'] or report['tracking']['clicks']):
        print('this campaign does not count opens or clicks')
        return
    if report['tracking']['opens']:
        print(f'opens   {opens["people"]} people ({opens["rate"]}%), {opens["total"]} times')
    if report['tracking']['clicks']:
        print(
            f'clicks  {clicks["people"]} people ({clicks["rate"]}%), {clicks["total"]} times, '
            f'{clicks["of_openers"]}% of those who opened'
        )
        for link in report['links']:
            print(f'  {link["people"]:>6} people  {link["url"]}')


def show(state: dict) -> None:
    counts = state['recipients']
    line = ', '.join(f'{n} {name}' for name, n in counts.items() if n)
    rate = state.get('bounce_rate')
    print(f'{state["id"]}  {state["status"]}  {line}' + (f'  bounce rate {rate}%' if rate else ''))
    if state['status_detail']:
        print(f'  {state["status_detail"]}')
    if state.get('send_at') and state['status'] == 'scheduled':
        print(f'  starts {state["send_at"]}')


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
    from_template = commands.add_parser('from-template', help='create a campaign from a template')
    from_template.add_argument('sender')
    from_template.add_argument('template_id')
    from_template.add_argument('people', type=Path, nargs='?', help='a CSV with an email column')
    from_template.add_argument('--audience', help='send to this audience (its id) instead of a CSV')
    from_template.add_argument('--subject', help="a subject instead of the template's")
    from_template.add_argument(
        '--text-file', type=Path, help="a text body instead of the template's"
    )
    from_template.add_argument('--html', type=Path, help="an HTML body instead of the template's")
    from_template.add_argument('--name', default='', help='your own label for the campaign')
    for each in (send, from_template):
        each.add_argument('--send-at', help='start then, e.g. 2026-03-01T09:00:00+01:00')
        each.add_argument('--no-opens', action='store_true', help='do not count opens')
        each.add_argument('--no-clicks', action='store_true', help='do not count clicks')
    for name in ('status', 'pause', 'resume', 'cancel', 'start', 'report'):
        sub = commands.add_parser(name)
        sub.add_argument('campaign_id')
        if name == 'status':
            sub.add_argument('--watch', action='store_true', help='follow it until it ends')
        if name == 'report':
            sub.add_argument('--by', choices=['hour', 'day'], default='hour')
    move = commands.add_parser('reschedule', help='move a scheduled campaign')
    move.add_argument('campaign_id')
    move.add_argument('send_at', help='e.g. 2026-03-02T09:00:00+01:00')
    args = parser.parse_args()

    api = Client.from_env()
    try:
        if args.command in ('send', 'from-template'):
            if bool(args.people) == bool(args.audience):
                raise SystemExit('Give a CSV of people, or --audience, but not both.')
            template = getattr(args, 'template_id', None)
            text_file = args.text_file
            result = api.create_campaign(
                args.sender,
                getattr(args, 'subject', None),
                read_people(args.people) if args.people else None,
                audience=args.audience,
                template=template,
                send_at=args.send_at,
                track_opens=False if args.no_opens else None,
                track_clicks=False if args.no_clicks else None,
                text=text_file.read_text(encoding='utf-8') if text_file else None,
                html=args.html.read_text(encoding='utf-8') if args.html else None,
                name=args.name,
            )
            when = f', starting {args.send_at}' if args.send_at else ''
            print(f'created {result["id"]}: {result["queued"]} to be sent{when}')
            for reason, count in sorted(result['skipped'].items()):
                print(f'  left out: {count} {reason}')
        elif args.command == 'report':
            show_report(api.campaign_report(args.campaign_id, by=args.by))
        elif args.command == 'reschedule':
            show(api.reschedule_campaign(args.campaign_id, args.send_at))
        elif args.command == 'start':
            show(api.start_campaign(args.campaign_id))
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
