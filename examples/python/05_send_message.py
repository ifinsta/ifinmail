"""Send an email through the API.  Needs a key with the mail.send scope and the address it
may send as (set when the key is created).

    python 05_send_message.py billing@example.com ana@example.org "Your invoice" "Thank you."

What the answer means: 202 is "accepted for delivery", not "delivered". The call is safe to
retry (an Idempotency-Key is sent for you), so a timeout never sends twice. What became of the
message shows up in the delivery report (06_delivery_report.py).
"""

import argparse

from ifinmail_client import Client, IfinmailError


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('sender')
    parser.add_argument('to')
    parser.add_argument('subject')
    parser.add_argument('text')
    parser.add_argument('--html', help='an HTML version of the body')
    args = parser.parse_args()

    api = Client.from_env()
    try:
        result = api.send(args.sender, [args.to], args.subject, text=args.text, html=args.html)
    except IfinmailError as exc:
        hints = {
            403: 'The key may not send as that address (or lacks mail.send).',
            409: 'The same Idempotency-Key is still being processed; wait and retry.',
            413: 'The message is too large.',
            422: 'The message was refused: ' + exc.detail,
            429: f'Too many messages; try again in {exc.retry_after or "a minute"} seconds.',
            502: 'The server could not hand the message to the mail system; try again.',
            503: 'Sending is paused or unavailable right now.',
        }
        raise SystemExit(f'Not sent. {hints.get(exc.status, exc.detail)}') from exc
    print(f"accepted: id={result['id']} recipients={result['recipients']}")


if __name__ == '__main__':
    main()
