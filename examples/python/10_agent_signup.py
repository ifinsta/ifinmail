"""An agent gets its own address, signs up somewhere, and reads the verification code back.

Needs the Agent inboxes plugin and a key with the agents.manage scope.

    python 10_agent_signup.py                 # creates an inbox, waits for mail, prints the code
    python 10_agent_signup.py --keep          # do not delete the inbox at the end

The sign-up itself is whatever your agent does (a browser tool, an API call). Here you trigger it
by hand: send any mail with a code in it to the address printed, for example from your phone.
"""

import argparse

from ifinmail_client import Client, IfinmailError


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--timeout', type=float, default=180, help='seconds to wait (default 180)')
    parser.add_argument('--keep', action='store_true', help='keep the inbox afterwards')
    args = parser.parse_args()

    api = Client.from_env()
    try:
        inbox = api.inboxes.create(label='sign-up example', ttl_hours=1)
    except IfinmailError as exc:
        raise SystemExit(f'Could not create an inbox: {exc}') from exc
    address = inbox['address']
    print(f'Inbox: {address} (expires {inbox["expires_at"]})')

    # Remember where the inbox stands *before* triggering the sign-up, so an old message
    # is never mistaken for the new one.
    since = api.inboxes.newest_uid(address)
    print('Now sign up with that address (or send it a message with a code). Waiting...')

    try:
        found = api.inboxes.wait(address, since_uid=since, timeout=args.timeout)
        if found is None:
            print('Nothing arrived in time.')
        else:
            print(f"From {found['from']}: {found['subject']!r}")
            print(f"code: {found['code']}   link: {found['link']}")
    finally:
        if not args.keep:
            api.inboxes.delete(address)
            print('Inbox deleted.')


if __name__ == '__main__':
    main()
