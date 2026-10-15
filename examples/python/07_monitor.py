"""A check for cron, Nagios, Icinga, Zabbix or a CI job: exit 0 ok, 1 warning, 2 critical.
Scope: audit.view.

    python 07_monitor.py
    python 07_monitor.py --max-bounce-rate 5

It fails (critical) when the server cannot be reached or a health check is failing, and warns
when a check needs attention or the bounce rate for the day is over the limit. A bounce rate over
fewer than 20 messages is noise, so it is ignored.
"""

import argparse

from ifinmail_client import Client, IfinmailError

OK, WARNING, CRITICAL = 0, 1, 2
FAILING = {'err', 'error', 'fail', 'failed'}
ATTENTION = {'warn', 'warning', 'unknown'}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--max-bounce-rate', type=float, default=5.0, help='percent (default 5)')
    args = parser.parse_args()
    api = Client.from_env(max_retries=1)

    try:
        health = api.health_full()
    except IfinmailError as exc:
        # 503 is the server saying "I am unwell" and it still sends the report.
        if exc.status == 503 and isinstance(exc.body, dict) and 'checks' in exc.body:
            health = exc.body
        else:
            print(f'CRITICAL: cannot read the health report: {exc}')
            return CRITICAL

    failing = [n for n, c in health['checks'].items() if str(c['status']).lower() in FAILING]
    attention = [n for n, c in health['checks'].items() if str(c['status']).lower() in ATTENTION]
    code = OK
    notes: list[str] = []
    if failing:
        code = CRITICAL
        notes.append('failing: ' + ', '.join(sorted(failing)))
    if attention:
        code = max(code, WARNING)
        notes.append('needs attention: ' + ', '.join(sorted(attention)))

    report = api.delivery('day')
    rate = report['bounce_rate']
    if rate is not None and report['final'] >= 20 and rate > args.max_bounce_rate:
        code = max(code, WARNING)
        notes.append(f"bounce rate {rate}% over {report['final']} messages")

    label = {OK: 'OK', WARNING: 'WARNING', CRITICAL: 'CRITICAL'}[code]
    print(f"{label}: " + ('; '.join(notes) if notes else 'all checks pass'))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
