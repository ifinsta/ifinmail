"""Create, list, change and delete mailboxes.  Scope: mail.manage.

    python 03_mailboxes.py list [--domain example.com]
    python 03_mailboxes.py create ana@example.com              # invited: she sets her own password
    python 03_mailboxes.py create ana@example.com --password 'a long passphrase'
    python 03_mailboxes.py quota ana@example.com 2048           # megabytes
    python 03_mailboxes.py pause ana@example.com                # cannot sign in until resumed
    python 03_mailboxes.py resume ana@example.com
    python 03_mailboxes.py delete ana@example.com
"""

import argparse

from ifinmail_client import Client, IfinmailError

MB = 1024 * 1024


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    listing = sub.add_parser('list')
    listing.add_argument('--domain')
    create = sub.add_parser('create')
    create.add_argument('address')
    create.add_argument('--password')
    create.add_argument('--quota-mb', type=int)
    quota = sub.add_parser('quota')
    quota.add_argument('address')
    quota.add_argument('megabytes', type=int, help='0 means unlimited')
    for name in ('pause', 'resume', 'delete'):
        sub.add_parser(name).add_argument('address')
    args = parser.parse_args()

    api = Client.from_env()
    try:
        if args.command == 'list':
            for box in api.mailboxes(args.domain):
                state = 'invited' if box['invite_pending'] else ('active' if box['is_active'] else 'paused')
                size = 'unlimited' if box['quota_bytes'] == 0 else f"{box['quota_bytes'] // MB} MB"
                print(f"{box['address']:<36} {state:<8} {size}")
        elif args.command == 'create':
            quota_bytes = args.quota_mb * MB if args.quota_mb is not None else None
            box = api.create_mailbox(args.address, args.password, quota_bytes)
            print('created', box['address'], '(invited)' if box['invite_pending'] else '')
        elif args.command == 'quota':
            api.update_mailbox(args.address, quota_bytes=args.megabytes * MB)
            print('quota set')
        elif args.command in ('pause', 'resume'):
            api.update_mailbox(args.address, is_active=args.command == 'resume')
            print(args.command + 'd', args.address)
        elif args.command == 'delete':
            api.delete_mailbox(args.address)
            print('deleted', args.address)
    except IfinmailError as exc:
        # 404 no such mailbox, 409 it already exists, 422 the value is not acceptable.
        raise SystemExit(f'{args.command} failed: {exc}') from exc


if __name__ == '__main__':
    main()
