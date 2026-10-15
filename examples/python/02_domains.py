"""List domains, add one, and check its DNS.  Scope: dns.manage.

    python 02_domains.py                      # list
    python 02_domains.py --add example.com    # add, then show what is still to do
"""

import argparse

from ifinmail_client import Client, IfinmailError

CHECKS = ('mx_verified', 'spf_verified', 'dkim_verified', 'dmarc_verified')


def show(domain: dict) -> None:
    marks = '  '.join(f"{c.split('_')[0].upper()}={'ok' if domain[c] else 'pending'}" for c in CHECKS)
    print(f"{domain['name']:<32} {marks}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--add', metavar='DOMAIN', help='add this domain')
    args = parser.parse_args()
    api = Client.from_env()

    if args.add:
        try:
            created = api.add_domain(args.add)
        except IfinmailError as exc:  # 422: not a valid domain name
            raise SystemExit(f'Could not add {args.add}: {exc.detail}') from exc
        print('added' if created.get('created') else 'already existed', args.add)
        for record in created.get('dns_records', []):
            print('  publish:', record)
        # Ask the server to look at the domain's DNS now (it also does this on a schedule).
        api.verify_domain(args.add)

    for domain in api.domains():
        show(domain)


if __name__ == '__main__':
    main()
