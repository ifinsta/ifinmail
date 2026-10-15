"""Receive events from ifinmail: a tiny receiver that checks every signature.

Standard library only. Run it behind your HTTPS proxy and point a webhook at it:

    export IFINMAIL_WEBHOOK_SECRET=whsec_...      # shown once when the webhook was created
    python 09_webhook_receiver.py --port 8080

Each event is printed once (retries carry the same X-Ifinmail-Event-Id, so they are skipped).
Answer 2xx quickly and do slow work later: the server waits at most 10 seconds and retries.
"""

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

from ifinmail_client import verify_webhook

SEEN: set[str] = set()  # use your database in a real application


def handle(event: dict) -> None:
    data = event['data']
    kind = event['type']
    if kind == 'message.bounced':
        print(f"bounced: {data['recipient']} ({data.get('category')}): {data['reason']}")
    elif kind == 'message.delivered':
        print(f"delivered: {data['message_id']} to {data['recipient']}")
    elif kind == 'message.received':
        print(f"received by {data['mailbox']}: {data['subject']!r} from {data['from']}")
    else:
        print(kind, json.dumps(data)[:200])


class Receiver(BaseHTTPRequestHandler):
    secret = ''

    def do_POST(self) -> None:  # noqa: N802 (the http.server name)
        length = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(min(length, 25 * 1024 * 1024))
        if not verify_webhook(self.secret, body, self.headers.get('X-Ifinmail-Signature', '')):
            self.send_response(401)
            self.end_headers()
            return
        event_id = self.headers.get('X-Ifinmail-Event-Id', '')
        if event_id not in SEEN:
            SEEN.add(event_id)
            handle(json.loads(body))
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args: object) -> None:  # quiet
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    Receiver.secret = os.environ.get('IFINMAIL_WEBHOOK_SECRET', '')
    if not Receiver.secret:
        raise SystemExit('Set IFINMAIL_WEBHOOK_SECRET to the secret shown when the webhook was created.')
    print(f'listening on :{args.port}')
    HTTPServer(('0.0.0.0', args.port), Receiver).serve_forever()


if __name__ == '__main__':
    main()
