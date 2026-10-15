"""Is the server up, and is my key working?  Needs a key with the console.access scope.

    python 01_hello.py
"""

from ifinmail_client import Client, IfinmailError


def main() -> None:
    api = Client.from_env()
    print('liveness:', api.health())  # no key needed
    try:
        status = api.status()  # needs the key
    except IfinmailError as exc:
        raise SystemExit(f'The key was refused: {exc}') from exc
    print(f"ok={status['ok']}  domains={status['domains']}  mailboxes={status['mailboxes']}")


if __name__ == '__main__':
    main()
