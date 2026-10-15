"""Sender compliance: suppression list, one-click unsubscribe, and the bounce guard."""

from __future__ import annotations

from django.core import mail
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from backend.apps.accounts.tests import test_api_messages as send_base
from backend.apps.accounts.tests import test_api_v1 as base
from backend.apps.core.plugins.services import InstallationService
from backend.apps.mail.models import Suppression
from backend.apps.mail.services import compliance, delivery_events

PLUGIN = 'sender-compliance'
GOOD = dict(send_base.GOOD_MESSAGE)  # billing@ifinmail.test -> ana@example.org


@override_settings(CACHES=base.LOCMEM)
class ComplianceBase(send_base.SendBase):
    def setUp(self) -> None:
        super().setUp()
        from django.core.cache import cache

        cache.clear()
        self.auth, self.row = self.sender_key()

    def enable(self, **settings: object) -> None:
        InstallationService.install(PLUGIN, settings, 'root@ifinmail.test')

    def send_body(self, **overrides: object):  # noqa: ANN201
        return self.send({**GOOD, **overrides}, **self.auth)


class SuppressionTests(ComplianceBase):
    def test_suppressed_recipients_are_left_out_and_listed(self) -> None:
        self.enable()
        compliance.suppress('ifinmail.test', 'ana@example.org', Suppression.UNSUBSCRIBED)
        response = self.send_body(to=['ana@example.org', 'bob@example.org'])
        self.assertEqual(response.status_code, 202, response.content)
        self.assertEqual(response.json()['suppressed'], ['ana@example.org'])
        self.assertEqual(response.json()['recipients'], 1)
        self.assertEqual(mail.outbox[0].to, ['bob@example.org'])

    def test_nobody_left_is_refused(self) -> None:
        self.enable()
        compliance.suppress('ifinmail.test', 'ana@example.org', Suppression.BOUNCED)
        response = self.send_body()
        self.assertEqual(response.status_code, 422)
        self.assertEqual(mail.outbox, [])

    def test_suppression_is_per_sending_domain(self) -> None:
        self.enable()
        compliance.suppress('other.test', 'ana@example.org', Suppression.UNSUBSCRIBED)
        self.assertEqual(self.send_body().json()['suppressed'], [])

    def test_without_the_plugin_the_list_is_not_applied(self) -> None:
        compliance.suppress('ifinmail.test', 'ana@example.org', Suppression.UNSUBSCRIBED)
        self.assertEqual(self.send_body().status_code, 202)
        self.assertEqual(len(mail.outbox), 1)

    def test_the_api_adds_lists_and_removes(self) -> None:
        self.enable()
        added = self.call('post', '/api/v1/suppressions', key=self.auth['key'], secret=self.auth['secret'],
                          body={'address': 'Ana@Example.org', 'domain': 'ifinmail.test', 'detail': 'app unsubscribe'})
        self.assertEqual(added.status_code, 201, added.content)
        self.assertEqual(added.json()['address'], 'ana@example.org')
        again = self.call('post', '/api/v1/suppressions', key=self.auth['key'], secret=self.auth['secret'],
                          body={'address': 'ana@example.org', 'domain': 'ifinmail.test'})
        self.assertEqual(again.status_code, 409)
        foreign = self.call('post', '/api/v1/suppressions', key=self.auth['key'], secret=self.auth['secret'],
                            body={'address': 'x@example.org', 'domain': 'elsewhere.test'})
        self.assertEqual(foreign.status_code, 403)
        listed = self.call('get', '/api/v1/suppressions', key=self.auth['key'], secret=self.auth['secret']).json()
        self.assertEqual(listed['count'], 1)
        removed = self.call('delete', '/api/v1/suppressions/ifinmail.test/ana@example.org', key=self.key, secret=self.secret)
        self.assertEqual(removed.status_code, 204)  # the owner's key has mail.manage


class UnsubscribeTests(ComplianceBase):
    def test_bulk_mail_gets_rfc_8058_headers_and_the_link_works(self) -> None:
        self.enable()
        self.assertEqual(self.send_body(unsubscribe=True).status_code, 202)
        headers = mail.outbox[0].extra_headers
        self.assertEqual(headers['List-Unsubscribe-Post'], 'List-Unsubscribe=One-Click')
        url = headers['List-Unsubscribe'].strip('<>')
        path = '/' + url.split('://', 1)[1].split('/', 1)[1]
        page = self.client.get(path)
        self.assertContains(page, 'Unsubscribe?')
        self.assertFalse(Suppression.objects.exists())  # opening the link is not enough
        self.client.post(path, {'List-Unsubscribe': 'One-Click'})  # what Gmail sends
        row = Suppression.objects.get()
        self.assertEqual((row.domain, row.address, row.reason), ('ifinmail.test', 'ana@example.org', 'unsubscribed'))
        self.assertEqual(self.send_body().status_code, 422)  # never again

    def test_transactional_mail_has_no_unsubscribe_unless_asked(self) -> None:
        self.enable()
        self.send_body()
        self.assertNotIn('List-Unsubscribe', mail.outbox[0].extra_headers)
        InstallationService.configure(PLUGIN, {'unsubscribe': 'all'}, 'a')
        self.send_body()
        self.assertIn('List-Unsubscribe', mail.outbox[1].extra_headers)

    def test_bulk_mail_goes_to_one_recipient_per_message(self) -> None:
        self.enable()
        response = self.send_body(unsubscribe=True, to=['ana@example.org', 'bob@example.org'])
        self.assertEqual(response.status_code, 422)

    def test_a_forged_or_changed_link_does_nothing(self) -> None:
        token = compliance.unsubscribe_token('billing@ifinmail.test', 'ana@example.org')
        response = self.client.post(reverse('unsubscribe', args=[token[:-2] + 'xx']))
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Suppression.objects.exists())


class BounceTests(ComplianceBase):
    def deliver_lines(self, message_id: str, outcomes: list[tuple[str, str, str]]) -> None:
        delivery_events.handle_line(f'Oct 15 09:00:00 mail postfix/cleanup[1]: Q1: message-id=<{message_id}>')
        for to, dsn, status in outcomes:
            delivery_events.handle_line(
                f'Oct 15 09:00:01 mail postfix/smtp[2]: Q1: to=<{to}>, relay=mx.example.org[198.51.100.1]:25, '
                f'delay=1, dsn={dsn}, status={status} (host said: 550 5.1.1 <{to}>: User unknown)'
            )

    def test_an_address_that_does_not_exist_is_suppressed_from_the_log(self) -> None:
        self.enable()
        message_id = self.send_body(to=['ghost@example.org']).json()['id']
        self.deliver_lines(message_id, [('ghost@example.org', '5.1.1', 'bounced')])
        row = Suppression.objects.get()
        self.assertEqual((row.address, row.reason), ('ghost@example.org', 'bounced'))
        self.assertEqual(self.send_body(to=['ghost@example.org']).status_code, 422)

    def test_a_temporary_failure_is_not_suppressed(self) -> None:
        self.enable()
        message_id = self.send_body().json()['id']
        self.deliver_lines(message_id, [('ana@example.org', '4.2.2', 'deferred')])
        self.assertFalse(Suppression.objects.exists())

    def test_too_many_bounces_pause_the_key_until_resumed(self) -> None:
        self.enable(bounce_limit=5)
        compliance.count(self.row.prefix, delivered=45, bounced=6)  # 11.8% of 51
        response = self.send_body()
        self.assertEqual(response.status_code, 403)
        self.assertIn('paused', response.json()['detail'])
        compliance.resume(self.row.prefix)
        self.assertEqual(self.send_body().status_code, 202)

    def test_a_few_bounces_on_little_mail_are_noise(self) -> None:
        self.enable(bounce_limit=5)
        compliance.count(self.row.prefix, delivered=5, bounced=3)
        self.assertEqual(self.send_body().status_code, 202)


class ConsoleTests(ComplianceBase):
    def test_the_page_lists_adds_removes_and_resumes(self) -> None:
        self.enable(bounce_limit=5)
        self.client.force_login(self.owner, backend=base.MODEL_BACKEND)
        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()
        url = reverse('accounts:suppressions_action')
        self.client.post(url, {'action': 'add', 'address': 'x@example.org', 'domain': 'ifinmail.test'})
        self.assertContains(self.client.get(reverse('accounts:suppressions')), 'x@example.org')
        compliance.count(self.row.prefix, delivered=40, bounced=20)
        self.assertContains(self.client.get(reverse('accounts:suppressions')), 'paused for bounces')
        self.client.post(url, {'action': 'resume', 'prefix': self.row.prefix})
        self.assertIsNone(compliance.paused(self.row.prefix))
        self.client.post(url, {'action': 'remove', 'address': 'x@example.org', 'domain': 'ifinmail.test'})
        self.assertFalse(Suppression.objects.exists())
