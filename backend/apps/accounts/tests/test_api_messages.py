"""POST /api/v1/messages: who may send as whom, how much, and what is never trusted."""

from __future__ import annotations

import json
from datetime import timedelta
from smtplib import SMTPServerDisconnected
from unittest.mock import patch

from django.core import mail
from django.core.cache import cache
from django.utils import timezone

from backend.apps.accounts.models import APIToken, MailUser
from backend.apps.accounts.services.tokens import (
    TokenError,
    TokenService,
    key_id,
    normalize_senders,
    sender_allowed,
)
from backend.apps.accounts.tests import test_api_v1 as base
from backend.apps.core.platform.models import AuditEvent
from backend.apps.domains.models import Domain
from backend.apps.mail.services import containment

URL = '/api/v1/messages'
GOOD_MESSAGE = {
    'from': 'billing@ifinmail.test',
    'to': ['ana@example.org'],
    'subject': 'Your invoice',
    'text': 'It is attached to your account.',
}


def capabilities(**values: dict[str, str]):
    """Patch the Outbound policy plugin's capability values for one test."""
    from backend.apps.core.plugins.services import InstallationService

    def fake(capability: str) -> dict[str, str]:
        return dict(values.get(capability, {}))

    return patch.object(InstallationService, 'capability_values', side_effect=fake)


class SendBase(base.ApiBase):
    def sender_key(self, senders: list[str] | None = None, **kwargs: object):
        row, token = TokenService.create(
            self.owner,
            'mailer',
            ['mail.send'],
            expires_in_days=30,
            allowed_senders=senders if senders is not None else ['billing@ifinmail.test'],
            **kwargs,  # type: ignore[arg-type]
        )
        return {'key': key_id(row.prefix), 'secret': token.split('.', 2)[2]}, row

    def send(self, body: dict | None = None, *, headers: dict | None = None, **auth: str):
        if not auth:
            auth, _ = self.sender_key()
        return self.call(
            'post',
            URL,
            key=auth['key'],
            secret=auth['secret'],
            body=body if body is not None else GOOD_MESSAGE,
            extra=headers,
        )


class SendingHappyPathTests(SendBase):
    def test_a_message_is_accepted_and_built_correctly(self) -> None:
        response = self.send(
            {
                **GOOD_MESSAGE,
                'cc': ['bob@example.org'],
                'bcc': ['audit@example.org'],
                'reply_to': 'support@ifinmail.test',
                'html': '<p>Hello <b>Ana</b></p>',
            }
        )
        self.assertEqual(response.status_code, 202, response.content)
        body = response.json()
        self.assertEqual(body['status'], 'queued')
        self.assertEqual(body['recipients'], 3)
        self.assertTrue(body['id'].endswith('@ifinmail.test'))
        (sent,) = mail.outbox
        self.assertEqual(sent.from_email, 'billing@ifinmail.test')
        self.assertEqual(sent.to, ['ana@example.org'])
        self.assertEqual(sent.cc, ['bob@example.org'])
        self.assertEqual(
            sorted(sent.recipients()), ['ana@example.org', 'audit@example.org', 'bob@example.org']
        )
        self.assertEqual(sent.reply_to, ['support@ifinmail.test'])
        self.assertEqual(sent.extra_headers['Message-ID'], f'<{body["id"]}>')
        self.assertEqual(sent.alternatives[0].mimetype, 'text/html')
        self.assertNotIn(
            'audit@example.org', sent.message().as_string().split('\n\n')[0]
        )  # no Bcc header

    def test_html_only_gets_a_text_part(self) -> None:
        response = self.send({**GOOD_MESSAGE, 'text': None, 'html': '<p>Hi &amp; welcome</p>'})
        self.assertEqual(response.status_code, 202, response.content)
        self.assertEqual(mail.outbox[0].body.strip(), 'Hi & welcome')

    def test_the_audit_trail_names_the_key_and_never_the_content(self) -> None:
        self.send({**GOOD_MESSAGE, 'subject': 'Secret plans', 'text': 'launch codes'})
        event = AuditEvent.objects.get(action='api_message_sent')
        self.assertIn('api:ifm_', event.user)
        self.assertIn('billing@ifinmail.test', event.detail)
        self.assertIn('example.org', event.detail)
        self.assertNotIn('Secret plans', event.detail)
        self.assertNotIn('launch codes', event.detail)
        self.assertNotIn('ana@example.org', event.detail)  # domains, not people

    def test_it_feeds_the_counters_containment_reads(self) -> None:
        with patch.object(containment, 'record_send') as record:
            self.send({**GOOD_MESSAGE, 'to': ['a@x.org', 'b@x.org']})
        record.assert_called_once()
        self.assertEqual(record.call_args.args[0], 'billing@ifinmail.test')
        self.assertEqual(sorted(record.call_args.args[1]), ['a@x.org', 'b@x.org'])

    def test_record_send_uses_the_same_keys_and_script_as_rspamd(self) -> None:
        class Redis:
            calls: list[tuple] = []

            def eval(self, *args: object) -> int:
                self.calls.append(args)
                return 1

        client = Redis()
        containment.record_send('Billing@IfinMail.test', ['A@x.org', 'b@y.org'], client=client)
        script, nkeys, *rest = client.calls[0]
        self.assertEqual(nkeys, 3)
        self.assertEqual(
            rest[:3],
            [
                'ifinmail:out:billing@ifinmail.test:m',
                'ifinmail:out:billing@ifinmail.test:r',
                'ifinmail:out:billing@ifinmail.test:d',
            ],
        )
        self.assertEqual(rest[3:5], [3600, 2])  # window, number of addresses
        self.assertEqual(len(rest[5:]), 2 + 2)  # two addresses, two domains
        self.assertIn("redis.call('INCR', KEYS[1])", script)


class SendingKeyRulesTests(SendBase):
    def test_a_sending_key_must_name_its_senders(self) -> None:
        with self.assertRaises(TokenError):
            TokenService.create(self.owner, 'x', ['mail.send'], expires_in_days=30)
        with self.assertRaises(TokenError):
            TokenService.create(
                self.owner,
                'x',
                ['mail.send'],
                expires_in_days=30,
                allowed_senders=['a@nowhere.test'],
            )

    def test_sender_entries_are_validated_and_matched(self) -> None:
        self.assertEqual(
            normalize_senders(
                [' Billing@IfinMail.test ', '*@ifinmail.test', 'billing@ifinmail.test']
            ),
            ['billing@ifinmail.test', '*@ifinmail.test'],
        )
        for bad in ('plain', '@ifinmail.test', 'a b@ifinmail.test', '*@unknown.test'):
            with self.assertRaises(TokenError):
                normalize_senders([bad])
        allowed = ['billing@ifinmail.test', '*@news.ifinmail.test']
        self.assertTrue(sender_allowed(allowed, 'BILLING@ifinmail.test'))
        self.assertTrue(sender_allowed(allowed, 'anyone@news.ifinmail.test'))
        self.assertFalse(sender_allowed(allowed, 'ceo@ifinmail.test'))
        self.assertFalse(sender_allowed(allowed, 'billing@evil.test'))
        self.assertFalse(sender_allowed([], 'billing@ifinmail.test'))

    def test_only_what_the_key_names_can_be_used_as_from(self) -> None:
        response = self.send({**GOOD_MESSAGE, 'from': 'ceo@ifinmail.test'})
        self.assertEqual(response.status_code, 403)
        self.assertIn('may not send as ceo@ifinmail.test', response.json()['detail'])
        self.assertEqual(mail.outbox, [])

    def test_a_wildcard_allows_any_address_on_that_domain_only(self) -> None:
        auth, _ = self.sender_key(['*@ifinmail.test'])
        self.assertEqual(
            self.send({**GOOD_MESSAGE, 'from': 'any@ifinmail.test'}, **auth).status_code, 202
        )
        self.assertEqual(
            self.send({**GOOD_MESSAGE, 'from': 'any@other.test'}, **auth).status_code, 403
        )

    def test_a_removed_domain_stops_the_key_at_send_time(self) -> None:
        auth, _ = self.sender_key()
        Domain.objects.filter(name='ifinmail.test').delete()
        response = self.send(**auth)
        self.assertEqual(response.status_code, 403)
        self.assertIn('not a domain on this server', response.json()['detail'])

    def test_the_scope_is_required_and_other_scopes_do_not_send(self) -> None:
        for scopes in (['mail.manage'], ['console.access', 'dns.manage']):
            row, token = TokenService.create(self.owner, 'n', scopes, expires_in_days=30)
            response = self.send(key=key_id(row.prefix), secret=token.split('.', 2)[2])
            self.assertEqual(response.status_code, 403)
        self.assertEqual(mail.outbox, [])

    def test_a_support_role_cannot_even_mint_a_sending_key(self) -> None:
        from backend.apps.accounts.services.roles import RoleService

        helper = MailUser.objects.create_user('help@ifinmail.test', base.GOOD, is_staff=True)
        RoleService.assign(helper, 'support')
        with self.assertRaises(TokenError):
            TokenService.create(
                helper,
                'x',
                ['mail.send'],
                expires_in_days=30,
                allowed_senders=['billing@ifinmail.test'],
            )

    def test_the_owner_losing_the_scope_stops_the_key(self) -> None:
        from backend.apps.accounts.services.roles import RoleService

        helper = MailUser.objects.create_user('ops@ifinmail.test', base.GOOD, is_staff=True)
        RoleService.assign(helper, 'administrator')
        row, token = TokenService.create(
            helper,
            'ops',
            ['mail.send'],
            expires_in_days=30,
            allowed_senders=['billing@ifinmail.test'],
        )
        auth = {'key': key_id(row.prefix), 'secret': token.split('.', 2)[2]}
        self.assertEqual(self.send(**auth).status_code, 202)
        RoleService.assign(helper, 'support')
        self.assertEqual(self.send(**auth).status_code, 403)


class SendingInputTests(SendBase):
    def test_bad_input_is_refused_and_nothing_is_sent(self) -> None:
        cases = {
            'no body': {**GOOD_MESSAGE, 'text': None},
            'blank body': {**GOOD_MESSAGE, 'text': '   '},
            'no recipient': {**GOOD_MESSAGE, 'to': []},
            'multi-line subject': {**GOOD_MESSAGE, 'subject': 'Hi\nBcc: evil@x.org'},
            'bad address': {**GOOD_MESSAGE, 'to': ['not-an-address']},
            'header injection in to': {**GOOD_MESSAGE, 'to': ['a@x.org\nBcc: evil@x.org']},
            'display name': {**GOOD_MESSAGE, 'to': ['Ana <ana@example.org>']},
            'comma list in one entry': {**GOOD_MESSAGE, 'to': ['a@x.org,b@x.org']},
            'injection in reply_to': {**GOOD_MESSAGE, 'reply_to': 'a@x.org\r\nX-Evil: 1'},
            'too many recipients': {**GOOD_MESSAGE, 'to': [f'u{i}@x.org' for i in range(101)]},
            'unknown from': {**GOOD_MESSAGE, 'from': 'nonsense'},
        }
        for name, body in cases.items():
            with self.subTest(case=name):
                response = self.send(body)
                self.assertIn(response.status_code, (403, 422), (name, response.content))
        self.assertEqual(mail.outbox, [])

    def test_extra_fields_cannot_add_headers_or_attachments(self) -> None:
        response = self.send({**GOOD_MESSAGE, 'headers': {'X-Evil': '1'}, 'attachments': ['x']})
        self.assertEqual(response.status_code, 202)
        self.assertNotIn('X-Evil', mail.outbox[0].extra_headers)

    def test_duplicate_recipients_are_counted_once(self) -> None:
        response = self.send({**GOOD_MESSAGE, 'to': ['a@x.org', 'A@X.org'], 'cc': ['a@x.org']})
        self.assertEqual(response.json()['recipients'], 1)


class OutboundPolicyTests(SendBase):
    def test_recipients_per_message_follow_the_plugin(self) -> None:
        with capabilities(**{'sending.recipient_limits': {'per_message': '2'}}):
            ok = self.send({**GOOD_MESSAGE, 'to': ['a@x.org', 'b@x.org']})
            over = self.send({**GOOD_MESSAGE, 'to': ['a@x.org', 'b@x.org', 'c@x.org']})
        self.assertEqual(ok.status_code, 202)
        self.assertEqual(over.status_code, 422)
        self.assertIn('at most 2 recipients', over.json()['detail'])

    def test_blocked_destinations_cover_addresses_domains_and_subdomains(self) -> None:
        blocked = {'sending.blocked_destinations': {'domains': 'spam.example, bad@x.org'}}
        with capabilities(**blocked):
            for recipient in ('a@spam.example', 'a@mail.spam.example', 'bad@x.org'):
                with self.subTest(recipient=recipient):
                    response = self.send({**GOOD_MESSAGE, 'to': [recipient]})
                    self.assertEqual(response.status_code, 403)
            fine = self.send({**GOOD_MESSAGE, 'to': ['ok@x.org', 'a@notspam.example']})
        self.assertEqual(fine.status_code, 202)

    def test_internal_only_mailboxes_may_only_write_to_hosted_domains(self) -> None:
        policy = {'sending.internal_only': {'mailboxes': 'billing@ifinmail.test'}}
        with capabilities(**policy):
            outside = self.send()
            inside = self.send({**GOOD_MESSAGE, 'to': ['staff@ifinmail.test']})
        self.assertEqual(outside.status_code, 403)
        self.assertEqual(inside.status_code, 202)

    def test_messages_per_minute_and_per_day_for_the_from_address(self) -> None:
        auth, _ = self.sender_key()
        with capabilities(**{'sending.rate_limit': {'per_minute': '2', 'per_day': '3'}}):
            first = self.send(**auth)
            second = self.send(**auth)
            third = self.send(**auth)
        self.assertEqual([first.status_code, second.status_code], [202, 202])
        self.assertEqual(third.status_code, 429)
        self.assertIn('Retry-After', third)

    def test_a_paused_mailbox_cannot_send_through_a_key(self) -> None:
        with patch.object(containment, 'paused', return_value={'billing@ifinmail.test': {}}):
            response = self.send()
        self.assertEqual(response.status_code, 403)
        self.assertIn('paused', response.json()['detail'])
        self.assertEqual(mail.outbox, [])


class SendingCapTests(SendBase):
    def test_the_daily_recipient_cap_counts_recipients_and_names_the_wait(self) -> None:
        auth, _ = self.sender_key(send_limit_per_day=3)
        self.assertEqual(
            self.send({**GOOD_MESSAGE, 'to': ['a@x.org', 'b@x.org']}, **auth).status_code, 202
        )
        over = self.send({**GOOD_MESSAGE, 'to': ['c@x.org', 'd@x.org']}, **auth)
        self.assertEqual(over.status_code, 429)
        self.assertIn('daily recipient limit of 3 is used up', over.json()['detail'])
        self.assertGreater(int(over['Retry-After']), 0)
        self.assertLessEqual(int(over['Retry-After']), 86400)
        # The refused attempt did not use up the cap.
        self.assertEqual(self.send({**GOOD_MESSAGE, 'to': ['c@x.org']}, **auth).status_code, 202)
        self.assertEqual(len(mail.outbox), 2)

    def test_the_default_cap_applies_when_a_key_has_none(self) -> None:
        with patch.dict('os.environ', {'API_SEND_LIMIT_PER_DAY': '1'}):
            auth, _ = self.sender_key()
            self.assertEqual(self.send(**auth).status_code, 202)
            self.assertEqual(self.send(**auth).status_code, 429)

    def test_each_key_has_its_own_cap(self) -> None:
        first, _ = self.sender_key(send_limit_per_day=1)
        second, _ = self.sender_key(send_limit_per_day=1)
        self.assertEqual(self.send(**first).status_code, 202)
        self.assertEqual(self.send(**second).status_code, 202)

    def test_a_relay_failure_is_a_502_and_gives_the_cap_back(self) -> None:
        auth, _ = self.sender_key(send_limit_per_day=1)
        with patch(
            'django.core.mail.message.EmailMessage.send', side_effect=SMTPServerDisconnected('down')
        ):
            failed = self.send(**auth)
        self.assertEqual(failed.status_code, 502)
        self.assertNotIn('down', failed.content.decode())  # no internals
        self.assertEqual(self.send(**auth).status_code, 202)

    def test_a_quota_store_outage_refuses_rather_than_sending_unlimited(self) -> None:
        auth, _ = self.sender_key()
        with patch.object(cache, 'incr', side_effect=RuntimeError('cache down')):
            response = self.send(**auth)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(mail.outbox, [])


class IdempotencyTests(SendBase):
    def test_a_retry_with_the_same_key_sends_once(self) -> None:
        auth, _ = self.sender_key()
        first = self.send(headers={'HTTP_IDEMPOTENCY_KEY': 'order-1001'}, **auth)
        again = self.send(headers={'HTTP_IDEMPOTENCY_KEY': 'order-1001'}, **auth)
        self.assertEqual((first.status_code, again.status_code), (202, 202))
        self.assertEqual(first.json(), again.json())
        self.assertEqual(len(mail.outbox), 1)

    def test_the_same_key_with_a_different_message_is_refused(self) -> None:
        auth, _ = self.sender_key()
        self.send(headers={'HTTP_IDEMPOTENCY_KEY': 'k1'}, **auth)
        other = self.send(
            {**GOOD_MESSAGE, 'subject': 'Something else'},
            headers={'HTTP_IDEMPOTENCY_KEY': 'k1'},
            **auth,
        )
        self.assertEqual(other.status_code, 422)
        self.assertEqual(len(mail.outbox), 1)

    def test_a_failed_attempt_can_be_retried_with_the_same_key(self) -> None:
        auth, _ = self.sender_key()
        with patch.object(containment, 'paused', return_value={'billing@ifinmail.test': {}}):
            self.assertEqual(
                self.send(headers={'HTTP_IDEMPOTENCY_KEY': 'k2'}, **auth).status_code, 403
            )
        self.assertEqual(self.send(headers={'HTTP_IDEMPOTENCY_KEY': 'k2'}, **auth).status_code, 202)

    def test_a_request_still_in_progress_is_a_409_and_keys_are_per_api_key(self) -> None:
        auth, row = self.sender_key()
        message = json.dumps(GOOD_MESSAGE).encode()  # noqa: F841  (documents the payload)
        from backend.apps.mail.serializers import MessageIn
        from backend.apps.mail.services.messages import digest

        fingerprint = digest(MessageIn.model_validate(GOOD_MESSAGE).model_dump_json(by_alias=True))
        cache.set(
            f'apiidem:ifm_{row.prefix}:busy', {'state': 'pending', 'fingerprint': fingerprint}, 60
        )
        busy = self.send(headers={'HTTP_IDEMPOTENCY_KEY': 'busy'}, **auth)
        self.assertEqual(busy.status_code, 409)
        other, _ = self.sender_key()
        self.assertEqual(
            self.send(headers={'HTTP_IDEMPOTENCY_KEY': 'busy'}, **other).status_code, 202
        )

    def test_an_overlong_key_is_refused(self) -> None:
        response = self.send(headers={'HTTP_IDEMPOTENCY_KEY': 'x' * 65})
        self.assertEqual(response.status_code, 422)


class MigrationAndConsoleTests(SendBase):
    def test_the_migration_grants_the_new_code_to_the_roles_that_hold_everything(self) -> None:
        import importlib

        from django.apps import apps

        from backend.apps.accounts.models import Role

        migration = importlib.import_module('backend.apps.accounts.migrations.0010_api_key_sending')
        Role.objects.all().delete()
        Role.objects.create(key='owner', name='Owner', permissions=['mail.manage'])
        Role.objects.create(key='administrator', name='Administrator', permissions=[])
        Role.objects.create(key='support', name='Support', permissions=['console.access'])
        migration.grant(apps, None)
        migration.grant(apps, None)  # idempotent
        self.assertIn('mail.send', Role.objects.get(key='owner').permissions)
        self.assertEqual(Role.objects.get(key='owner').permissions.count('mail.send'), 1)
        self.assertIn('mail.send', Role.objects.get(key='administrator').permissions)
        self.assertNotIn('mail.send', Role.objects.get(key='support').permissions)

    def test_the_seed_gives_support_no_sending(self) -> None:
        from backend.apps.accounts.types.permissions import SEED_ROLES

        by_key = {r['key']: r['permissions'] for r in SEED_ROLES}
        self.assertIn('mail.send', by_key['owner'])
        self.assertIn('mail.send', by_key['administrator'])
        self.assertNotIn('mail.send', by_key['support'])

    def test_the_console_creates_a_sending_key_and_lists_its_senders(self) -> None:
        from django.urls import reverse

        self.client.force_login(self.owner, backend=base.MODEL_BACKEND)
        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()
        create = reverse('accounts:api_key_create')
        refused = self.client.post(
            create,
            {
                'name': 'Mailer',
                'scopes': ['mail.send'],
                'expires_in_days': '30',
                'confirm_password': base.GOOD,
            },
            follow=True,
        )
        self.assertContains(refused, 'must name the addresses it may send as')
        self.client.post(
            create,
            {
                'name': 'Mailer',
                'scopes': ['mail.send'],
                'expires_in_days': '30',
                'senders': 'billing@ifinmail.test\n*@ifinmail.test',
                'send_limit_per_day': '250',
                'confirm_password': base.GOOD,
            },
        )
        row = APIToken.objects.get(name='Mailer')
        self.assertEqual(row.allowed_senders, ['billing@ifinmail.test', '*@ifinmail.test'])
        self.assertEqual(row.send_limit_per_day, 250)
        page = self.client.get(reverse('accounts:api_keys')).content.decode()
        self.assertIn('Sends as billing@ifinmail.test, *@ifinmail.test', page)

    def test_the_mailbox_profile_form_does_not_offer_sending(self) -> None:
        from backend.apps.accounts.forms.mailboxes import TokenCreateForm

        offered = [code for code, _ in TokenCreateForm().fields['scopes'].choices]
        self.assertNotIn('mail.send', offered)
        self.assertIn('mail.manage', offered)

    def test_the_contract_lists_the_operation_with_its_scope(self) -> None:
        spec = self.client.get('/api/v1/openapi.json').json()
        operation = spec['paths']['/api/v1/messages']['post']
        self.assertEqual(operation['x-required-scope'], 'mail.send')
        self.assertIn('202', operation['responses'])
        names = {p['name'] for p in operation.get('parameters', [])}
        self.assertIn('Idempotency-Key', names)
        self.assertEqual(
            sorted(spec['components']['schemas']['MessageIn']['properties']),
            ['bcc', 'cc', 'from', 'html', 'reply_to', 'subject', 'text', 'to', 'unsubscribe'],
        )
        self.assertTrue(timedelta(0) < timedelta(days=1))
