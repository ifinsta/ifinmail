"""What happened to the mail this server sent.  Scope: audit.view.

    python 06_delivery_report.py            # last 24 hours
    python 06_delivery_report.py week

"Sent" means the receiving server accepted the message. It does not say whether it reached the
inbox or the spam folder: that is only visible from the receiver's side.
"""

import sys

from ifinmail_client import Client


def main() -> None:
    period = sys.argv[1] if len(sys.argv) > 1 else 'day'
    report = Client.from_env().delivery(period)

    rate = report['bounce_rate']
    print(f"{report['label']}: accepted={report['sent']} retried={report['deferred']} "
          f"failed={report['bounced']} bounce rate={'n/a' if rate is None else f'{rate}%'}")
    verdict = report['verdict']
    print(f"-> {verdict['headline']}\n   {verdict['next']}")

    if report['reasons']:
        print('\nWhy mail did not go through:')
        for reason in report['reasons']:
            print(f"  {reason['count']:>4}  {reason['label']}  - {reason['hint']}")
    if report['providers']:
        print('\nBy provider:')
        for item in report['providers'][:5]:
            print(f"  {item['provider']:<20} accepted={item['sent']} failed={item['bounced']}")


if __name__ == '__main__':
    main()
