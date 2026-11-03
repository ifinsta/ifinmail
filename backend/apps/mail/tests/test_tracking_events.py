"""Webhook events for opens and clicks (Delivery events plugin, campaigns with tracking).

What these tests pin down: that a person's first open and the first click of each link make an
event and repeats do not; that bots and ``HEAD`` requests make none; that the event reaches the
console's webhooks and the campaign key's own and nobody else's; that a failure to queue an event
never costs the person their pixel or their redirect; and what the receiver is sent.
"""

from __future__ import annotations

import json
import socket
from unittest.mock import patch
from urllib.parse import urlsplit

from backend.apps.core.plugins.services import InstallationService
from backend.apps.mail.models import WebhookDelivery
from backend.apps.mail.services import tracking, webhooks
from backend.apps.mail.tests.test_delivery_events import PLUGIN, Receiver, fake_dns
from backend.apps.mail.tests.test_tracking import TrackBase

OPENED, CLICKED = 'message.opened', 'message.clicked'
HTML = (
    '<p>Hi</p><a href="https://shop.example.com/a?u={{id}}">A</a> '
    '<a href="https://shop.example.com/b">B</a>'
)


class EventsBase(TrackBase):
    def setUp(self) -> None:
        super().setUp()
        InstallationService.install(PLUGIN, {}, 'a')
        dns = patch.object(socket, 'getaddrinfo', side_effect=fake_dns)
        dns.start()
        self.addCleanup(dns.stop)
        self.receiver = Receiver()
        post = patch.object(webhooks, '_post', side_effect=self.receiver)
        post.start()
        self.addCleanup(post.stop)
        queue = patch.object(webhooks, '_schedule')  # tests deliver explicitly
        queue.start()
        self.addCleanup(queue.stop)

    def hook(self, events=(OPENED, CLICKED), **kw):  # noqa: ANN001, ANN201
        row, _ = webhooks.create_endpoint(
            name=kw.pop('name', 'app'), url='https://hooks.example.com/in', events=events, **kw
        )
        return row

    def campaign_run(self, n: int = 3):  # noqa: ANN201
        campaign = self.run_campaign(n, html=HTML, recipients=[
            {'email': f'p{i}@example.org', 'merge': {'id': str(i)}} for i in range(n)
        ])  # fmt: skip
        return campaign

    def events(self, kind: str | None = None) -> list[WebhookDelivery]:
        rows = WebhookDelivery.objects.exclude(event_type__startswith='message.queued')
        rows = rows.exclude(event_type='webhook.ping')
        return list(rows.filter(event_type=kind) if kind else rows)


class OpenedTests(EventsBase):
    def test_the_first_open_makes_an_event_and_repeats_do_not(self) -> None:
        self.hook()
        campaign = self.campaign_run()
        for _ in range(3):
            self.client.get(self.pixel(0))
        found = self.events(OPENED)
        self.assertEqual(len(found), 1)
        data = found[0].payload['data']
        self.assertEqual(data['recipient'], 'p0@example.org')
        self.assertEqual(data['campaign'], str(campaign.pk))
        self.assertEqual(data['sender'], 'news@ifinmail.test')
        self.assertEqual(data['message_id'], self.person(campaign).message_id)
        self.assertEqual(self.person(campaign).opens, 3)  # still counted

    def test_each_person_has_their_own(self) -> None:
        self.hook()
        self.campaign_run()
        for i in range(3):
            self.client.get(self.pixel(i))
        self.assertEqual(len(self.events(OPENED)), 3)

    def test_a_bot_or_a_head_request_makes_no_event(self) -> None:
        self.hook()
        self.campaign_run()
        self.client.head(self.pixel(0))
        self.client.get(self.pixel(0), HTTP_USER_AGENT='Googlebot')
        self.assertEqual(self.events(), [])
        self.client.get(self.pixel(0))  # a person, afterwards: this is still the first open
        self.assertEqual(len(self.events(OPENED)), 1)

    def test_a_campaign_that_does_not_count_opens_makes_none(self) -> None:
        self.hook()
        campaign = self.run_campaign(
            2,
            html=HTML,
            track_opens=False,
            recipients=[{'email': f'p{i}@example.org', 'merge': {'id': str(i)}} for i in range(2)],
        )
        path = urlsplit(tracking.open_url(self.person(campaign).pk)).path
        self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(self.events(), [])

    def test_the_event_id_follows_from_the_person_so_it_is_made_once(self) -> None:
        self.hook()
        campaign = self.campaign_run(1)
        person = self.person(campaign)
        tracking._emit(tracking.EventType.OPENED, person.pk)
        tracking._emit(tracking.EventType.OPENED, person.pk)
        self.assertEqual(len(self.events(OPENED)), 1)


class ClickedTests(EventsBase):
    def click(self, person: int, link: int):  # noqa: ANN201
        return self.client.get(self.tracked('c', person)[link])

    def test_the_first_click_of_a_link_makes_an_event_with_the_address_it_went_to(self) -> None:
        self.hook()
        campaign = self.campaign_run()
        for _ in range(3):
            self.assertEqual(self.click(1, 0).status_code, 302)
        found = self.events(CLICKED)
        self.assertEqual(len(found), 1)
        data = found[0].payload['data']
        self.assertEqual(data['url'], 'https://shop.example.com/a?u=1')  # this person's value
        self.assertEqual(data['recipient'], 'p1@example.org')
        self.assertEqual(data['campaign'], str(campaign.pk))
        self.assertEqual(self.person(campaign, 'p1@example.org').clicks, 3)

    def test_another_link_or_another_person_is_another_event(self) -> None:
        self.hook()
        self.campaign_run()
        self.click(0, 0)
        self.click(0, 1)
        self.click(1, 0)
        urls = sorted(e.payload['data']['url'] for e in self.events(CLICKED))
        self.assertEqual(
            urls,
            [
                'https://shop.example.com/a?u=0',
                'https://shop.example.com/a?u=1',
                'https://shop.example.com/b',
            ],
        )

    def test_a_scanner_is_sent_on_and_makes_no_event(self) -> None:
        self.hook()
        self.campaign_run()
        response = self.client.get(self.tracked('c', 0)[0], HTTP_USER_AGENT='Proofpoint')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.events(), [])


class WhoGetsThemTests(EventsBase):
    def test_a_webhook_gets_only_the_events_it_asked_for(self) -> None:
        self.hook(events=(CLICKED,))
        self.campaign_run()
        self.client.get(self.pixel(0))
        self.assertEqual(self.events(), [])
        self.client.get(self.tracked('c', 0)[0])
        self.assertEqual(len(self.events(CLICKED)), 1)

    def test_the_console_and_the_campaigns_own_key_get_them_and_other_keys_do_not(self) -> None:
        console = self.hook(name='console')
        own = self.hook(name='own', owner_prefix=self.row.prefix)
        other = self.hook(name='other', owner_prefix='someoneelse1')
        self.campaign_run()
        self.client.get(self.pixel(0))
        owners = {d.endpoint_id for d in self.events(OPENED)}
        self.assertEqual(owners, {console.pk, own.pk})
        self.assertNotIn(other.pk, owners)

    def test_nothing_is_queued_without_the_delivery_events_plugin(self) -> None:
        self.hook()
        self.campaign_run()
        InstallationService.uninstall(PLUGIN, 'a')
        response = self.client.get(self.pixel(0))
        self.assertEqual(response.status_code, 200)  # the pixel still answers
        self.assertEqual(self.events(), [])

    def test_the_new_events_can_be_subscribed_to_and_unknown_ones_cannot(self) -> None:
        row = self.hook(events=(OPENED, CLICKED))
        self.assertEqual(row.events, [CLICKED, OPENED])
        with self.assertRaises(webhooks.WebhookError):
            self.hook(events=('message.opened', 'message.read'))


class NeverInTheWayTests(EventsBase):
    def test_a_failure_to_queue_never_costs_the_person_their_pixel_or_redirect(self) -> None:
        self.hook()
        campaign = self.campaign_run()
        with patch.object(webhooks, 'emit', side_effect=RuntimeError('broker down')):
            self.assertEqual(self.client.get(self.pixel(0)).status_code, 200)
            response = self.client.get(self.tracked('c', 0)[0])
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], 'https://shop.example.com/a?u=0')
        person = self.person(campaign)
        self.assertEqual((person.opens, person.clicks), (1, 1))  # and both were counted


class DeliveryTests(EventsBase):
    def test_the_receiver_gets_a_signed_event_with_the_type_and_the_data(self) -> None:
        row = self.hook()
        self.campaign_run(1)
        self.client.get(self.pixel(0))
        delivery = self.events(OPENED)[0]
        self.assertTrue(webhooks.deliver(str(delivery.pk)))
        ((url, body, headers),) = self.receiver.calls
        self.assertEqual(url, 'https://hooks.example.com/in')
        self.assertEqual(headers['X-Ifinmail-Event'], OPENED)
        sent = json.loads(body)
        self.assertEqual(sent['type'], OPENED)
        self.assertEqual(sent['data']['recipient'], 'p0@example.org')
        self.assertTrue(sent['id'].startswith('evt_'))
        self.assertEqual(row.pk, delivery.endpoint_id)
