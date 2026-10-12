#!/usr/bin/env python3
"""Capacity probe: how much does one ifinmail server take before it slows or errors?

Standard library only. Run it from a *different* machine against a server you own, ideally a
staging copy: it generates real load. Prints a Markdown table for docs/enterprise-evidence/.

    capacity_probe.py --base https://mail.example.com
    capacity_probe.py --base https://mail.example.com --levels 1,5,10,25,50 --seconds 20
    capacity_probe.py --base https://mail.example.com \\
        --smtp mail.example.com:587 --smtp-user probe@example.com \\
        --smtp-password-file ./pw --smtp-to probe@example.com --smtp-count 50

HTTP measures the console's public pages (no login, no writes). SMTP submits real messages to
one recipient you name, over STARTTLS with authentication; the per-login send limit (see
rspamd/local.d/ratelimit.conf) will answer with 4xx once it is reached, which is reported.
"""

from __future__ import annotations

import argparse
import smtplib
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

PAGES = ('/health/', '/accounts/login/')


def _fetch(url: str, timeout: float) -> tuple[float, bool]:
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
            response.read()
            ok = 200 <= response.status < 400
    except (urllib.error.URLError, OSError):
        ok = False
    return time.perf_counter() - start, ok


def _http_level(base: str, clients: int, seconds: float, timeout: float) -> dict[str, float]:
    stop = time.monotonic() + seconds
    lock = threading.Lock()
    latencies: list[float] = []
    errors = 0

    def worker(index: int) -> None:
        nonlocal errors
        n = index
        while time.monotonic() < stop:
            took, ok = _fetch(base + PAGES[n % len(PAGES)], timeout)
            n += 1
            with lock:
                latencies.append(took)
                if not ok:
                    errors += 1

    began = time.monotonic()
    with ThreadPoolExecutor(max_workers=clients) as pool:
        list(pool.map(worker, range(clients)))
    elapsed = time.monotonic() - began
    latencies.sort()

    def pct(p: float) -> float:
        return latencies[min(len(latencies) - 1, int(len(latencies) * p))] * 1000 if latencies else 0

    return {
        'clients': clients,
        'requests': len(latencies),
        'rps': len(latencies) / elapsed if elapsed else 0,
        'p50': pct(0.50),
        'p95': pct(0.95),
        'p99': pct(0.99),
        'errors': errors,
    }


def _smtp(args: argparse.Namespace) -> dict[str, float]:
    host, _, port = args.smtp.partition(':')
    password = open(args.smtp_password_file, encoding='utf-8').read().strip()
    sent = deferred = failed = 0
    began = time.monotonic()
    with smtplib.SMTP(host, int(port or 587), timeout=30) as server:
        server.starttls(context=ssl.create_default_context())
        server.login(args.smtp_user, password)
        for i in range(args.smtp_count):
            body = f'From: {args.smtp_user}\r\nTo: {args.smtp_to}\r\nSubject: probe {i}\r\n\r\nx\r\n'
            try:
                server.sendmail(args.smtp_user, [args.smtp_to], body)
                sent += 1
            except smtplib.SMTPResponseException as exc:
                if 400 <= exc.smtp_code < 500:
                    deferred += 1
                else:
                    failed += 1
    elapsed = time.monotonic() - began
    return {'sent': sent, 'deferred': deferred, 'failed': failed, 'per_second': sent / elapsed}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--base', required=True, help='https://mail.example.com')
    parser.add_argument('--levels', default='1,5,10,25', help='concurrent clients, comma separated')
    parser.add_argument('--seconds', type=float, default=15, help='duration of each level')
    parser.add_argument('--timeout', type=float, default=10)
    parser.add_argument('--smtp', help='host:587 for the submission test')
    parser.add_argument('--smtp-user')
    parser.add_argument('--smtp-password-file')
    parser.add_argument('--smtp-to')
    parser.add_argument('--smtp-count', type=int, default=20)
    args = parser.parse_args()

    base = args.base.rstrip('/')
    print(f'## Capacity probe: {base}\n')
    print(f'Pages: {", ".join(PAGES)} · {args.seconds:g} s per level · from {time.strftime("%F %T")}\n')
    print('| Clients | Requests | Req/s | p50 ms | p95 ms | p99 ms | Errors |')
    print('|---|---|---|---|---|---|---|')
    knee = None
    baseline = None
    for level in (int(x) for x in args.levels.split(',')):
        row = _http_level(base, level, args.seconds, args.timeout)
        baseline = baseline or row['p95'] or 1
        if knee is None and (row['errors'] or row['p95'] > 4 * baseline):
            knee = level
        print(
            f'| {row["clients"]} | {row["requests"]} | {row["rps"]:.1f} | {row["p50"]:.0f} '
            f'| {row["p95"]:.0f} | {row["p99"]:.0f} | {row["errors"]} |'
        )
        sys.stdout.flush()
        if row['errors'] > row['requests'] * 0.5:
            print('\nMore than half the requests failed; stopping.')
            break
    print()
    if knee:
        print(f'**Degradation begins at {knee} concurrent clients** (errors, or p95 above 4x the '
              f'single-client p95).')
    else:
        print('No degradation up to the highest level tested.')
    if args.smtp:
        if not (args.smtp_user and args.smtp_password_file and args.smtp_to):
            print('\n--smtp needs --smtp-user, --smtp-password-file and --smtp-to', file=sys.stderr)
            return 2
        result = _smtp(args)
        print(
            f'\n**Submission:** {result["sent"]:.0f} accepted, {result["deferred"]:.0f} deferred '
            f'(4xx, e.g. the send limit), {result["failed"]:.0f} rejected; '
            f'{result["per_second"]:.1f} messages/s.'
        )
    print('\nMeasured from one client machine: network latency to the server is included.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
