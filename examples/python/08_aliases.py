"""Aliases: an address that forwards to another.  Scope: mail.manage.

    python 08_aliases.py list [--domain example.com]
    python 08_aliases.py add sales@example.com ana@example.com
    python 08_aliases.py remove <alias id from the list>
"""

import argparse

from ifinmail_client import Client, IfinmailError


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('list').add_argument('--domain')
    add = sub.add_parser('add')
    add.add_argument('source')
    add.add_argument('destination')
    sub.add_parser('remove').add_argument('alias_id')
    args = parser.parse_args()

    api = Client.from_env()
    try:
        if args.command == 'list':
            for alias in api.aliases(args.domain):
                print(f"{alias['id']}  {alias['source']} -> {alias['destination']}")
        elif args.command == 'add':
            alias = api.create_alias(args.source, args.destination)
            print('created', alias['id'])
        else:
            api.delete_alias(args.alias_id)
            print('removed')
    except IfinmailError as exc:
        raise SystemExit(f'{args.command} failed: {exc}') from exc


if __name__ == '__main__':
    main()
