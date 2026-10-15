"""Create many mailboxes from a CSV file, safely.  Scope: mail.manage.

The file has one mailbox per line; only the first column is required:

    address,quota_mb,password
    ana@example.com,2048,
    ben@example.com,1024,
    cleo@example.com,,

A blank password creates an *invited* mailbox (its owner sets the password from a link), which
is the right default for people. Rerunning the same file is safe: mailboxes that exist are
skipped, not recreated.

    python 04_bulk_provision.py people.csv --dry-run
    python 04_bulk_provision.py people.csv
"""

import argparse
import csv
import sys

from ifinmail_client import Client, IfinmailError

MB = 1024 * 1024


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('csv_file')
    parser.add_argument('--dry-run', action='store_true', help='check the file, change nothing')
    args = parser.parse_args()

    with open(args.csv_file, newline='', encoding='utf-8') as handle:
        rows = [r for r in csv.DictReader(handle) if (r.get('address') or '').strip()]
    if not rows:
        print('Nothing to do: the file has no addresses.')
        return 0

    api = Client.from_env()
    created = skipped = failed = 0
    for row in rows:
        address = row['address'].strip().lower()
        quota = (row.get('quota_mb') or '').strip()
        password = (row.get('password') or '').strip() or None
        if args.dry_run:
            print(f'would create {address}')
            continue
        try:
            api.create_mailbox(address, password, int(quota) * MB if quota else None)
            created += 1
            print(f'created  {address}')
        except IfinmailError as exc:
            if exc.status == 409:  # already there
                skipped += 1
                print(f'exists   {address}')
            else:  # 422 bad address or weak password, 403 key lacks the scope, ...
                failed += 1
                print(f'FAILED   {address}: {exc.detail}', file=sys.stderr)
                if exc.status in (401, 403):
                    return 2  # nothing else will work either
    print(f'\n{created} created, {skipped} already existed, {failed} failed')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
