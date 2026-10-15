"""Delivery Events: signed webhooks for what became of mail sent through the API."""

from __future__ import annotations

import json
import os
import socket
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from backend.apps.accounts.tests import test_api_messages as send_base
from backend.apps.accounts.tests import test_api_v1 as base
from backend.apps.core.plugins.services import InstallationService
from backend.apps.core.plugins.services import secrets as plugin_secrets
from backend.apps.mail.models import WebhookDelivery, WebhookEndpoint
from backend.apps.mail.services import delivery_events, webhooks

PLUGIN = 'delivery-events'
PUBLIC = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('203.0.113.10', 443))]
_REAL_GETADDRINFO = socket.getaddrinfo


def fake_dns(host, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN201
    """Webhook hosts in the tests resolve to a public address; everything else (Redis, the
    database) resolves as usual so nothing waits on a connection to a fake address."""
    if isinstance(host, str) and (host.endswith('.example') or '.example.' in host or host.endswith('example.com')):
        return PUBLIC
    return _REAL_GETADDRINFO(host, *args, **kwargs)


def resolves_to(address: str):  # noqa: ANN201
    return patch.object(
        socket, 'getaddrinfo', return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 443))]
    )


class Receiver:
    """Stands in for the HTTP POST; records what was sent and answers with ``status``."""

    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.calls: list[tuple[str, bytes, dict]] = []

    def __call__(self, url: str, body: bytes, headers: dict) -> int:
        self.calls.append((url, body, headers))
        if isinstance(self.status, Exception):
            raise self.status
        return self.status


@override_settings(CACHES=base.LOCMEM)
class EventsBase(send_base.SendBase):
    def setUp(self) -> None:
        super().setUp()
        self.dns = patch.object(socket, 'getaddrinfo', side_effect=fake_dns)
        self.dns.start()
        self.addCleanup(self.dns.stop)
        self.receiver = Receiver()
        poster = patch.object(webhooks, '_post', side_effect=self.receiver)
        poster.start()
        self.addCleanup(poster.stop)
        # The on_commit hook queues a Celery task; tests deliver explicitly.
        queue = patch.object(webhooks, '_schedule')
        queue.start()
        self.addCleanup(queue.stop)

    def enable(self, **settings: object) -> None:
        InstallationService.install(PLUGIN, settings, 'root@ifinmail.test')

    def endpoint(self, events=('message.bounced', 'message.delivered', 'message.queued', 'message.deferred'), **kw):  # noqa: ANN001, ANN201
        return webhooks.create_endpoint(name=kw.pop('name', 'app'), url=kw.pop('url', 'https://hooks.example.com/in'), events=events, **kw)


class UrlSafetyTests(EventsBase):
    def setUp(self) -> None:
        super().setUp()
        self.enable()

    def test_only_public_https_addresses(self) -> None:
        for url in ('ftp://x.example.com', 'hooks.example.com', 'https://user:pw@x.example.com/'):
            with self.subTest(url=url), self.assertRaises(webhooks.WebhookError):
                webhooks.check_url(url)
        with self.assertRaisesMessage(webhooks.WebhookError, 'https'):
            webhooks.check_url('http://hooks.example.com/')
        for host in ('localhost', 'redis', 'api', 'metadata.google.internal', 'x.localhost'):
            with self.subTest(host=host), self.assertRaises(webhooks.WebhookError):
                webhooks.check_url(f'https://{host}/hook')
        self.assertEqual(webhooks.check_url('https://hooks.example.com/in'), 'https://hooks.example.com/in')

    def test_addresses_that_reach_this_server_are_refused_whatever_the_name(self) -> None:
        for address in ('127.0.0.1', '169.254.169.254', '0.0.0.0'):
            with self.subTest(address=address), resolves_to(address), self.assertRaises(webhooks.WebhookError):
                webhooks.check_url('https://innocent.example.com/')
        with resolves_to('172.18.0.5'), self.assertRaisesMessage(webhooks.WebhookError, 'private'):
            webhooks.check_url('https://innocent.example.com/')

    def test_private_networks_and_http_when_the_plugin_allows_them(self) -> None:
        InstallationService.configure(PLUGIN, {'allow_private': True, 'allow_http': True}, 'a')
        with resolves_to('192.168.1.20'):
            self.assertTrue(webhooks.check_url('http://n8n.lan.example/hook'))
        with resolves_to('127.0.0.1'), self.assertRaises(webhooks.WebhookError):
            webhooks.check_url('http://loop.example/hook')  # never this server


class EndpointTests(EventsBase):
    def test_webhooks_need_the_plugin(self) -> None:
        with self.assertRaisesMessage(webhooks.WebhookError, 'Install'):
            self.endpoint()

    def test_secret_is_shown_once_and_stored_encrypted(self) -> None:
        self.enable()
        row, secret = self.endpoint()
        self.assertTrue(secret.startswith('whsec_'))
        self.assertNotEqual(row.secret, secret)
        self.assertEqual(plugin_secrets.decrypt(row.secret), secret)

    def test_events_are_checked(self) -> None:
        self.enable()
        for events in ([], ['message.opened'], ['message.received']):
            with self.subTest(events=events), self.assertRaises(webhooks.WebhookError):
                self.endpoint(events=events)


class DeliveryTests(EventsBase):
    def setUp(self) -> None:
        super().setUp()
        self.enable()
        self.row, self.secret = self.endpoint()

    def emit(self, **kw):  # noqa: ANN201
        made = webhooks.emit('message.bounced', {'message_id': 'm1'}, **kw)
        return made, WebhookDelivery.objects.order_by('-created_at').first()

    def test_a_delivered_event_is_signed_and_verifiable(self) -> None:
        _, delivery = self.emit()
        self.assertTrue(webhooks.deliver(str(delivery.pk)))
        url, body, headers = self.receiver.calls[0]
        self.assertEqual(url, 'https://hooks.example.com/in')
        self.assertEqual(headers['X-Ifinmail-Event'], 'message.bounced')
        self.assertEqual(headers['X-Ifinmail-Event-Id'], delivery.event_id)
        self.assertTrue(webhooks.verify(self.secret, body, headers['X-Ifinmail-Signature']))
        self.assertFalse(webhooks.verify('whsec_wrong', body, headers['X-Ifinmail-Signature']))
        self.assertFalse(webhooks.verify(self.secret, body + b' ', headers['X-Ifinmail-Signature']))
        self.assertEqual(json.loads(body)['type'], 'message.bounced')
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, 'delivered')

    def test_a_failure_is_retried_later_then_given_up(self) -> None:
        self.receiver.status = 500
        _, delivery = self.emit()
        self.assertFalse(webhooks.deliver(str(delivery.pk)))
        delivery.refresh_from_db()
        self.assertEqual((delivery.status, delivery.attempts), ('pending', 1))
        self.assertGreater(delivery.next_attempt_at, timezone.now() + timedelta(seconds=50))
        self.assertFalse(webhooks.deliver(str(delivery.pk)))  # not due yet: not attempted
        self.assertEqual(len(self.receiver.calls), 1)
        InstallationService.configure(PLUGIN, {'max_attempts': 2}, 'a')
        WebhookDelivery.objects.filter(pk=delivery.pk).update(next_attempt_at=timezone.now())
        self.assertEqual(webhooks.sweep(), 1)
        delivery.refresh_from_db()
        self.assertEqual((delivery.status, delivery.attempts), ('failed', 2))
        self.row.refresh_from_db()
        self.assertIsNotNone(self.row.failing_since)

    def test_410_switches_the_webhook_off(self) -> None:
        self.receiver.status = 410
        _, delivery = self.emit()
        webhooks.deliver(str(delivery.pk))
        self.row.refresh_from_db()
        self.assertFalse(self.row.active)
        self.assertEqual(webhooks.emit('message.bounced', {}), 0)  # off: nothing queued

    def test_an_address_that_now_resolves_inside_is_refused_at_delivery(self) -> None:
        _, delivery = self.emit()
        with resolves_to('10.0.0.5'):
            self.assertFalse(webhooks.deliver(str(delivery.pk)))
        self.assertEqual(self.receiver.calls, [])  # DNS rebinding: never sent
        delivery.refresh_from_db()
        self.assertIn('private', delivery.last_error)

    def test_routing_console_and_key_webhooks(self) -> None:
        own, _ = self.endpoint(name='key', owner_prefix='abc123')
        webhooks.emit('message.bounced', {}, key_prefix='zzz999')
        self.assertEqual(WebhookDelivery.objects.filter(endpoint=own).count(), 0)
        webhooks.emit('message.bounced', {}, key_prefix='abc123')
        self.assertEqual(WebhookDelivery.objects.filter(endpoint=own).count(), 1)
        self.assertEqual(WebhookDelivery.objects.filter(endpoint=self.row).count(), 2)

    def test_an_event_is_queued_once_per_webhook(self) -> None:
        self.assertEqual(webhooks.emit('message.bounced', {}, event_id='evt_same'), 1)
        self.assertEqual(webhooks.emit('message.bounced', {}, event_id='evt_same'), 0)

    def test_a_timeout_is_an_error_not_a_crash(self) -> None:
        self.receiver.status = TimeoutError('timed out')
        _, delivery = self.emit()
        self.assertFalse(webhooks.deliver(str(delivery.pk)))
        delivery.refresh_from_db()
        self.assertIn('TimeoutError', delivery.last_error)


class LogScanTests(EventsBase):
    def setUp(self) -> None:
        super().setUp()
        self.enable()
        self.row, _ = self.endpoint()

    def test_api_sends_become_queued_delivered_and_bounced_events(self) -> None:
        response = self.send({**send_base.GOOD_MESSAGE, 'to': ['ana@example.org', 'bob@gmail.com']})
        message_id = response.json()['id']
        queued = WebhookDelivery.objects.get(event_type='message.queued')
        self.assertEqual(queued.payload['data']['message_id'], message_id)
        lines = [
            f'Oct 15 09:00:00 mail postfix/cleanup[11]: 4ABC123: message-id=<{message_id}>',
            'Oct 15 09:00:01 mail postfix/smtp[12]: 4ABC123: to=<ana@example.org>, relay=mx.example.org[198.51.100.1]:25, delay=1, dsn=2.0.0, status=sent (250 2.0.0 OK)',
            'Oct 15 09:00:02 mail postfix/smtp[12]: 4ABC123: to=<bob@gmail.com>, relay=gmail-smtp-in.l.google.com[142.250.1.1]:25, delay=1, dsn=5.7.25, status=bounced (host said: 550-5.7.25 The IP address sending this message does not have a PTR record, bob@gmail.com)',
            'Oct 15 09:00:03 mail postfix/smtp[12]: 9OTHER9: to=<x@example.net>, relay=a[1.2.3.4]:25, dsn=2.0.0, status=sent (250 ok)',
        ]
        made = sum(delivery_events.handle_line(line) for line in lines)
        self.assertEqual(made, 2)  # the unrelated message produced nothing
        delivered = WebhookDelivery.objects.get(event_type='message.delivered')
        self.assertEqual(delivered.payload['data']['recipient'], 'ana@example.org')
        bounced = WebhookDelivery.objects.get(event_type='message.bounced')
        self.assertEqual(bounced.payload['data']['dsn'], '5.7.25')
        self.assertEqual(bounced.payload['data']['category'], 'reverse_dns')
        self.assertNotIn('bob@gmail.com', bounced.payload['data']['reason'])  # scrubbed
        # The same log line twice is one event.
        self.assertEqual(delivery_events.handle_line(lines[1]), 0)

    def test_the_log_is_followed_from_the_end_and_across_rotation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'postfix.log'
            path.write_text('old line\n')
            self.assertEqual(delivery_events.read_new_lines(path), [])  # a fresh install
            with path.open('a') as handle:
                handle.write('new one\npartial')
            self.assertEqual(delivery_events.read_new_lines(path), ['new one'])
            with path.open('a') as handle:
                handle.write(' line\n')
            self.assertEqual(delivery_events.read_new_lines(path), ['partial line'])
            os.rename(path, Path(tmp) / 'postfix.log.1')
            path.write_text('after rotation\n')
            self.assertEqual(delivery_events.read_new_lines(path), ['after rotation'])

    def test_nothing_happens_without_the_plugin(self) -> None:
        InstallationService.uninstall(PLUGIN, 'a')
        self.send()
        self.assertFalse(WebhookDelivery.objects.exists())
        self.assertEqual(delivery_events.scan(), 0)


class WebhookApiTests(EventsBase):
    def setUp(self) -> None:
        super().setUp()
        self.enable()
        self.auth, self.key_row = self.sender_key()

    def api(self, method: str, path: str, body: dict | None = None):  # noqa: ANN201
        return self.call(method, path, key=self.auth['key'], secret=self.auth['secret'], body=body)

    def test_a_key_manages_its_own_webhooks(self) -> None:
        created = self.api('post', '/api/v1/webhooks', {'name': 'app', 'url': 'https://hooks.example.com/x', 'events': ['message.bounced']})
        self.assertEqual(created.status_code, 201, created.content)
        body = created.json()
        self.assertTrue(body['secret'].startswith('whsec_'))
        listing = self.api('get', '/api/v1/webhooks').json()
        self.assertEqual([w['id'] for w in listing], [body['id']])
        self.assertNotIn('secret', listing[0])
        ping = self.api('post', f"/api/v1/webhooks/{body['id']}/test")
        self.assertEqual(ping.json()['status'], 'delivered')
        deliveries = self.api('get', f"/api/v1/webhooks/{body['id']}/deliveries").json()
        self.assertEqual(deliveries['items'][0]['event_type'], 'webhook.ping')
        self.assertEqual(self.api('delete', f"/api/v1/webhooks/{body['id']}").status_code, 204)

    def test_another_key_cannot_see_or_touch_it(self) -> None:
        row, _ = self.endpoint()  # a console webhook
        other = self.api('get', f'/api/v1/webhooks/{row.pk}/deliveries')
        self.assertEqual(other.status_code, 404)
        self.assertEqual(self.api('delete', f'/api/v1/webhooks/{row.pk}').status_code, 404)

    def test_bad_requests(self) -> None:
        bad_url = self.api('post', '/api/v1/webhooks', {'name': 'a', 'url': 'https://localhost/x', 'events': ['message.bounced']})
        self.assertEqual(bad_url.status_code, 422)
        foreign_box = self.api('post', '/api/v1/webhooks', {'name': 'a', 'url': 'https://h.example.com/', 'events': ['message.received'], 'mailboxes': ['ceo@ifinmail.test']})
        self.assertEqual(foreign_box.status_code, 403)


class WebhookConsoleTests(EventsBase):
    def setUp(self) -> None:
        super().setUp()
        self.client.force_login(self.owner, backend=base.MODEL_BACKEND)
        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()

    def test_create_test_and_remove_from_the_console(self) -> None:
        self.assertContains(self.client.get(reverse('accounts:webhooks')), 'No events are being sent')
        self.enable()
        response = self.client.post(
            reverse('accounts:webhooks_create'),
            {'name': 'crm', 'url': 'https://hooks.example.com/crm', 'events': ['message.bounced']},
            follow=True,
        )
        self.assertContains(response, 'whsec_')
        row = WebhookEndpoint.objects.get(name='crm')
        self.assertEqual(row.owner_prefix, '')
        self.client.post(reverse('accounts:webhooks_action'), {'webhook': row.pk, 'action': 'test'})
        self.assertEqual(len(self.receiver.calls), 1)
        self.client.post(reverse('accounts:webhooks_action'), {'webhook': row.pk, 'action': 'delete'})
        self.assertFalse(WebhookEndpoint.objects.exists())
