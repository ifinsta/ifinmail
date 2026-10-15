"""The Python examples in ``examples/python`` run against the real API.

The client and every script are imported from the repository and pointed at the Django test
client (through an adapter that looks like ``requests.Session``), so a documented example cannot
drift from the API: a renamed field, a changed status code or a moved path fails here.
"""

from __future__ import annotations

import importlib
import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.core import mail
from django.test import SimpleTestCase, override_settings

from backend.apps.accounts.services.tokens import TokenService, key_id
from backend.apps.accounts.tests import test_api_v1 as base

EXAMPLES = Path(settings.BASE_DIR) / 'examples' / 'python'
LOCMEM = base.LOCMEM


def load(name: str):  # noqa: ANN201
    if str(EXAMPLES) not in sys.path:
        sys.path.insert(0, str(EXAMPLES))
    return importlib.import_module(name)


class DjangoSession:
    """What ``requests.Session`` is to the client, on top of the Django test client."""

    def __init__(self, client) -> None:  # noqa: ANN001
        self.client = client
        self.auth: tuple[str, str] | None = None
        self.calls: list[tuple[str, str]] = []

    def request(self, method, url, *, params=None, json=None, headers=None, timeout=None):  # noqa: ANN001, ANN201
        path = '/' + url.split('://', 1)[-1].split('/', 1)[-1]
        extra = {}
        if self.auth:
            extra['HTTP_AUTHORIZATION'] = base.basic(*self.auth)
        for name, value in (headers or {}).items():
            extra['HTTP_' + name.upper().replace('-', '_')] = value
        self.calls.append((method.upper(), path))
        fn = getattr(self.client, method.lower())
        kwargs = {'data': json_dumps(json), 'content_type': 'application/json'} if json is not None else {}
        response = fn(path, params or {}, **kwargs, **extra) if method.upper() == 'GET' else fn(path, **kwargs, **extra)
        return Reply(response)


def json_dumps(value):  # noqa: ANN001, ANN201
    return json.dumps(value)


class Reply:
    def __init__(self, response) -> None:  # noqa: ANN001
        self.status_code = response.status_code
        self.content = response.content
        self.text = response.content.decode('utf-8', 'replace')
        self.headers = {k: v for k, v in response.items()}

    def json(self):  # noqa: ANN201
        return json.loads(self.text)


@override_settings(CACHES=LOCMEM)
class ExampleBase(base.ApiBase):
    def setUp(self) -> None:
        super().setUp()
        self.module = load('ifinmail_client')
        self.session = DjangoSession(self.client)
        self.api = self.module.Client(
            'http://testserver', self.key, self.secret, session=self.session, max_retries=0
        )

    def sender(self, senders: list[str]):  # noqa: ANN201
        row, token = TokenService.create(
            self.owner, 'mailer', ['mail.send'], expires_in_days=30, allowed_senders=senders
        )
        return self.module.Client(
            'http://testserver', key_id(row.prefix), token.split('.', 2)[2], session=DjangoSession(self.client), max_retries=0
        )

    def run_script(self, name: str, *argv: str, client=None) -> tuple[int, str, str]:  # noqa: ANN001
        module = load(name)
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with (
            patch.object(sys, 'argv', [name + '.py', *argv]),
            patch.object(self.module.Client, 'from_env', classmethod(lambda cls, **kw: client or self.api)),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            try:
                result = module.main()
                code = result if isinstance(result, int) else 0
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
                if isinstance(exc.code, str):
                    err.write(exc.code)
        return code, out.getvalue(), err.getvalue()


class ClientTests(ExampleBase):
    def test_status_and_authentication(self) -> None:
        self.assertEqual(self.api.status()['ok'], True)
        bad = self.module.Client(
            'http://testserver', self.key, 'ifs_wrong', session=DjangoSession(self.client), max_retries=0
        )
        with self.assertRaises(self.module.IfinmailError) as caught:
            bad.status()
        self.assertEqual(caught.exception.status, 401)

    def test_mailbox_lifecycle(self) -> None:
        box = self.api.create_mailbox('ana@ifinmail.test')
        self.assertTrue(box['invite_pending'])
        self.assertEqual(self.api.mailbox('ana@ifinmail.test')['address'], 'ana@ifinmail.test')
        self.api.update_mailbox('ana@ifinmail.test', quota_bytes=1024 * 1024, is_active=False)
        self.assertFalse(self.api.mailbox('ana@ifinmail.test')['is_active'])
        with self.assertRaises(self.module.IfinmailError) as caught:
            self.api.create_mailbox('ana@ifinmail.test')
        self.assertEqual(caught.exception.status, 409)
        self.api.delete_mailbox('ana@ifinmail.test')
        with self.assertRaises(self.module.IfinmailError) as missing:
            self.api.mailbox('ana@ifinmail.test')
        self.assertEqual(missing.exception.status, 404)

    def test_paging_follows_every_page(self) -> None:
        for n in range(5):
            self.api.create_mailbox(f'user{n}@ifinmail.test', 'Correct-Horse-9-pass')
        with patch.object(self.module, 'PAGE_SIZE', 2):
            seen = [b['address'] for b in self.api.mailboxes('ifinmail.test')]
        self.assertEqual(len(seen), 5)
        self.assertEqual(len(set(seen)), 5)
        page_calls = [c for c in self.session.calls if c[0] == 'GET' and 'mailboxes' in c[1]]
        self.assertGreaterEqual(len(page_calls), 3)

    def test_aliases(self) -> None:
        self.api.create_mailbox('ana@ifinmail.test')
        alias = self.api.create_alias('sales@ifinmail.test', 'ana@ifinmail.test')
        self.assertIn(alias['id'], [a['id'] for a in self.api.aliases('ifinmail.test')])
        self.api.delete_alias(alias['id'])
        self.assertNotIn(alias['id'], [a['id'] for a in self.api.aliases()])

    def test_domains(self) -> None:
        names = [d['name'] for d in self.api.domains()]
        self.assertIn('ifinmail.test', names)
        self.assertEqual(self.api.domain('ifinmail.test')['name'], 'ifinmail.test')

    def test_sending_is_idempotent_and_reports_what_was_accepted(self) -> None:
        sender = self.sender(['billing@ifinmail.test'])
        first = sender.send('billing@ifinmail.test', ['ana@example.org'], 'Hi', text='Hello', idempotency_key='k-1')
        again = sender.send('billing@ifinmail.test', ['ana@example.org'], 'Hi', text='Hello', idempotency_key='k-1')
        self.assertEqual(first, again)
        self.assertEqual(first['status'], 'queued')
        self.assertEqual(len(mail.outbox), 1)  # the retry did not send a second message
        with self.assertRaises(self.module.IfinmailError) as caught:
            sender.send('someone-else@ifinmail.test', ['ana@example.org'], 'Hi', text='x')
        self.assertEqual(caught.exception.status, 403)

    def test_sandbox_round_trip(self) -> None:
        from backend.apps.core.plugins.services import InstallationService

        InstallationService.install('developer-sandbox', {}, 'root@ifinmail.test')
        row, token = TokenService.create(
            self.owner, 'ci', ['mail.send'], expires_in_days=30,
            allowed_senders=['billing@ifinmail.test'], sandbox=True,
        )
        ci = self.module.Client(
            'http://testserver', key_id(row.prefix), token.split('.', 2)[2],
            session=DjangoSession(self.client), max_retries=0,
        )
        ci.clear_sandbox()
        result = ci.send('billing@ifinmail.test', ['ana@example.org'], 'Welcome', text='Hi')
        self.assertEqual(result['status'], 'captured')
        self.assertEqual(mail.outbox, [])
        (captured,) = list(ci.sandbox_messages(to='ana@example.org'))
        self.assertEqual(captured['subject'], 'Welcome')

    def test_webhooks_round_trip_and_signature_check(self) -> None:
        import socket

        from backend.apps.core.plugins.services import InstallationService
        from backend.apps.mail.services import webhooks

        InstallationService.install('delivery-events', {}, 'root@ifinmail.test')
        row, token = TokenService.create(
            self.owner, 'app', ['mail.send'], expires_in_days=30,
            allowed_senders=['billing@ifinmail.test'],
        )
        app = self.module.Client(
            'http://testserver', key_id(row.prefix), token.split('.', 2)[2],
            session=DjangoSession(self.client), max_retries=0,
        )
        received: list[tuple[bytes, dict]] = []
        public = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('203.0.113.9', 443))]
        with patch.object(socket, 'getaddrinfo', return_value=public), patch.object(
            webhooks, '_post', side_effect=lambda url, body, headers: received.append((body, headers)) or 200
        ):
            hook = app.create_webhook('app', 'https://hooks.example.com/in', ['message.bounced'])
            answer = app.test_webhook(hook['id'])
        self.assertEqual(answer['status'], 'delivered')
        body, headers = received[0]
        self.assertTrue(self.module.verify_webhook(hook['secret'], body, headers['X-Ifinmail-Signature']))
        self.assertFalse(self.module.verify_webhook('whsec_other', body, headers['X-Ifinmail-Signature']))
        self.assertEqual([w['id'] for w in app.webhooks()], [hook['id']])
        app.delete_webhook(hook['id'])
        self.assertEqual(app.webhooks(), [])

    def test_a_rate_limit_is_waited_out(self) -> None:
        slept: list[float] = []
        calls = {'n': 0}
        real = self.session.request

        def limited(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            calls['n'] += 1
            if calls['n'] == 1:
                return SimpleNamespace(
                    status_code=429, content=b'{"detail": "slow down"}', text='{"detail": "slow down"}',
                    headers={'Retry-After': '3'}, json=lambda: {'detail': 'slow down'},
                )
            return real(*args, **kwargs)

        self.session.request = limited  # type: ignore[method-assign]
        self.api.max_retries = 2
        with patch.object(self.module.time, 'sleep', side_effect=slept.append):
            self.assertTrue(self.api.status()['ok'])
        self.assertEqual(slept, [3.0])

    def test_a_write_without_an_idempotency_key_is_not_retried(self) -> None:
        calls = {'n': 0}

        def unavailable(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            calls['n'] += 1
            return SimpleNamespace(
                status_code=503, content=b'{}', text='{}', headers={}, json=lambda: {}
            )

        self.session.request = unavailable  # type: ignore[method-assign]
        self.api.max_retries = 3
        with patch.object(self.module.time, 'sleep'), self.assertRaises(self.module.IfinmailError):
            self.api.create_mailbox('ana@ifinmail.test')
        self.assertEqual(calls['n'], 1)
        calls['n'] = 0
        with patch.object(self.module.time, 'sleep'), self.assertRaises(self.module.IfinmailError):
            self.api.status()  # a read is retried
        self.assertEqual(calls['n'], 4)

    def test_an_unreachable_server_is_one_clear_error(self) -> None:
        def down(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            raise ConnectionError('refused')

        self.session.request = down  # type: ignore[method-assign]
        with self.assertRaises(self.module.IfinmailError) as caught:
            self.api.status()
        self.assertEqual(caught.exception.status, 0)
        self.assertIn('could not reach', caught.exception.detail)


class ScriptTests(ExampleBase):
    def test_hello(self) -> None:
        code, out, _ = self.run_script('01_hello')
        self.assertEqual(code, 0)
        self.assertIn('ok=True', out)

    def test_domains_lists(self) -> None:
        code, out, _ = self.run_script('02_domains')
        self.assertEqual(code, 0)
        self.assertIn('ifinmail.test', out)

    def test_mailboxes_commands(self) -> None:
        self.assertEqual(self.run_script('03_mailboxes', 'create', 'ana@ifinmail.test')[0], 0)
        code, out, _ = self.run_script('03_mailboxes', 'list', '--domain', 'ifinmail.test')
        self.assertIn('ana@ifinmail.test', out)
        self.assertIn('invited', out)
        self.assertEqual(self.run_script('03_mailboxes', 'quota', 'ana@ifinmail.test', '2048')[0], 0)
        self.assertEqual(self.run_script('03_mailboxes', 'pause', 'ana@ifinmail.test')[0], 0)
        self.assertFalse(self.api.mailbox('ana@ifinmail.test')['is_active'])
        self.assertEqual(self.run_script('03_mailboxes', 'delete', 'ana@ifinmail.test')[0], 0)
        code, _, err = self.run_script('03_mailboxes', 'delete', 'ana@ifinmail.test')
        self.assertNotEqual(code, 0)
        self.assertIn('404', err)

    def test_bulk_provision_is_safe_to_rerun(self) -> None:
        import tempfile

        with tempfile.NamedTemporaryFile('w', suffix='.csv', delete=False) as handle:
            handle.write('address,quota_mb,password\nann@ifinmail.test,512,\nbo@ifinmail.test,,\n,,\n')
        dry = self.run_script('04_bulk_provision', handle.name, '--dry-run')
        self.assertEqual(dry[0], 0)
        self.assertEqual(list(self.api.mailboxes('ifinmail.test')), [])  # a dry run changes nothing
        first = self.run_script('04_bulk_provision', handle.name)
        self.assertIn('2 created, 0 already existed, 0 failed', first[1])
        second = self.run_script('04_bulk_provision', handle.name)
        self.assertIn('0 created, 2 already existed, 0 failed', second[1])
        self.assertEqual(second[0], 0)
        self.assertEqual(self.api.mailbox('ann@ifinmail.test')['quota_bytes'], 512 * 1024 * 1024)

    def test_bulk_provision_reports_a_bad_row(self) -> None:
        import tempfile

        with tempfile.NamedTemporaryFile('w', suffix='.csv', delete=False) as handle:
            handle.write('address\nnot-an-address\n')
        code, _, err = self.run_script('04_bulk_provision', handle.name)
        self.assertEqual(code, 1)
        self.assertIn('FAILED', err)

    def test_send_message(self) -> None:
        sender = self.sender(['billing@ifinmail.test'])
        code, out, _ = self.run_script(
            '05_send_message', 'billing@ifinmail.test', 'ana@example.org', 'Hi', 'Hello', client=sender
        )
        self.assertEqual(code, 0)
        self.assertIn('accepted', out)
        self.assertEqual(len(mail.outbox), 1)
        code, _, err = self.run_script(
            '05_send_message', 'other@ifinmail.test', 'ana@example.org', 'Hi', 'Hello', client=sender
        )
        self.assertNotEqual(code, 0)
        self.assertIn('may not send as that address', err)

    def test_delivery_report_and_monitor(self) -> None:
        code, out, _ = self.run_script('06_delivery_report')
        self.assertEqual(code, 0)
        self.assertIn('accepted=', out)
        code, out, _ = self.run_script('07_monitor')
        self.assertIn(code, (0, 1, 2))
        self.assertRegex(out, r'^(OK|WARNING|CRITICAL): ')

    def test_monitor_reads_the_report_a_503_carries(self) -> None:
        report = {'status': 'err', 'checks': {'database': {'status': 'err'}, 'disk': {'status': 'ok'}}}

        def unwell(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            raise self.module.IfinmailError(503, 'unwell', body=report)

        with patch.object(self.api, 'health_full', side_effect=unwell):
            code, out, _ = self.run_script('07_monitor')
        self.assertEqual(code, 2)
        self.assertIn('failing: database', out)

    def test_aliases_script(self) -> None:
        self.api.create_mailbox('ana@ifinmail.test')
        self.assertEqual(self.run_script('08_aliases', 'add', 'sales@ifinmail.test', 'ana@ifinmail.test')[0], 0)
        code, out, _ = self.run_script('08_aliases', 'list')
        self.assertIn('sales@ifinmail.test -> ana@ifinmail.test', out)


class FilesTests(SimpleTestCase):
    def test_every_script_has_a_docstring_a_main_and_no_secret(self) -> None:
        scripts = sorted(EXAMPLES.glob('0*.py'))
        self.assertGreaterEqual(len(scripts), 9)
        for path in scripts:
            text = path.read_text()
            with self.subTest(script=path.name):
                self.assertTrue(text.lstrip().startswith('"""'))
                self.assertIn("if __name__ == '__main__':", text)
                self.assertNotRegex(text, r'ifs_[A-Za-z0-9_-]{20,}')

    def test_the_readme_lists_every_script(self) -> None:
        readme = (EXAMPLES / 'README.md').read_text()
        for path in EXAMPLES.glob('0*.py'):
            self.assertIn(path.name, readme)
