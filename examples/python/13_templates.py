"""Keep your campaign messages on the server and send them again: create one, preview it, list it.
Needs a key with the marketing.send scope.

    python 13_templates.py new "Welcome" "Hi {{first_name|friend}}" body.txt --html body.html
    python 13_templates.py list
    python 13_templates.py show 4c1a...                    # and the merge tags it uses
    python 13_templates.py preview 4c1a... first_name=Ana offer="20% off"
    python 13_templates.py update 4c1a... --subject "New subject"
    python 13_templates.py delete 4c1a...

Then send it with ``11_marketing_campaign.py from-template SENDER 4c1a... --audience ID``.

A template is a subject and a text and/or html body with ``{{merge}}`` tags. ``preview`` fills them
the way a campaign would for one person (nothing is sent) and tells you which tags have no value
and no fallback: a campaign would skip anybody missing one. A campaign copies the template when it
is created, so editing or deleting a template never changes a campaign that exists.
"""

import argparse
from pathlib import Path

from ifinmail_client import Client, IfinmailError

HINTS = {
    403: 'The key lacks marketing.send, or Marketing is switched off.',
    404: 'No such template (or it belongs to another key).',
}


def read(path: Path | None) -> str | None:
    return path.read_text(encoding='utf-8') if path else None


def show(template: dict) -> None:
    print(f'{template["id"]}  {template["name"]}  -  {template["subject"]}')
    for tag in template['tags']:
        print(
            f'  {{{{{tag["name"]}}}}}'
            + ('  (needs a value or a fallback)' if tag['required'] else '')
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest='command', required=True)
    new = commands.add_parser('new', help='create a template')
    new.add_argument('name')
    new.add_argument('subject')
    new.add_argument('text_file', type=Path, nargs='?', help='the plain-text body')
    new.add_argument('--html', type=Path, help='an HTML version of the body')
    commands.add_parser('list', help='your templates')
    for name in ('show', 'delete'):
        commands.add_parser(name).add_argument('template_id')
    preview = commands.add_parser('preview', help='fill in the tags for one person')
    preview.add_argument('template_id')
    preview.add_argument('values', nargs='*', help='tag=value, as many as you like')
    preview.add_argument('--email', default='', help='fills {{email}}')
    update = commands.add_parser('update', help='change a template')
    update.add_argument('template_id')
    update.add_argument('--name')
    update.add_argument('--subject')
    update.add_argument('--text-file', type=Path)
    update.add_argument('--html', type=Path)
    args = parser.parse_args()

    api = Client.from_env()
    try:
        if args.command == 'new':
            made = api.create_template(
                args.name, args.subject, text=read(args.text_file), html=read(args.html)
            )
            print(f'created {made["id"]}')
            show(made)
        elif args.command == 'list':
            for template in api.templates():
                show(template)
        elif args.command == 'show':
            show(api.template(args.template_id))
        elif args.command == 'preview':
            merge = dict(value.split('=', 1) for value in args.values if '=' in value)
            shown = api.preview_template(args.template_id, merge, args.email)
            print(f'Subject: {shown["subject"]}')
            print(shown['text'] or shown['html'])
            if shown['missing']:
                print('No value and no fallback for: ' + ', '.join(shown['missing']))
        elif args.command == 'update':
            changes = {
                'name': args.name,
                'subject': args.subject,
                'text': read(args.text_file),
                'html': read(args.html),
            }
            show(api.update_template(args.template_id, **{k: v for k, v in changes.items() if v}))
        else:
            api.delete_template(args.template_id)
            print('deleted')
    except IfinmailError as exc:
        raise SystemExit(f'Failed. {HINTS.get(exc.status) or exc.detail}') from exc


if __name__ == '__main__':
    main()
