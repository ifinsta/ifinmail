"""Scheduled campaigns: created now, started by the runner when their time comes.

What these tests pin down: that a time without a zone, in the past or absurdly far is refused; that
nothing is sent before the time and everything is after it; that a scheduled campaign can be moved,
started early or cancelled but not paused; that one the server missed by hours is held for a person
instead of being sent late; and that the lists are checked at sending time, not at creation.
"""

from __future__ import annotations

from datetime import timedelta

from django.core import mail
from django.utils import timezone

from backend.apps.mail.models import Campaign, MarketingOptOut
from backend.apps.mail.services import campaign_runner, marketing
from backend.apps.mail.tests.test_marketing import SENDER, MarketingBase, people


class ScheduleBase(MarketingBase):
    def setUp(self) -> None:
        super().setUp()
        self.auth, self.row = self.marketing_key()

    def api(self, method: str, path: str, body: dict | None = None, auth: dict | None = None):
        auth = auth or self.auth
        return self.call(method, path, key=auth['key'], secret=auth['secret'], body=body)

    def schedule(self, when, **body: object):  # noqa: ANN001, ANN201
        payload = {
            'from': SENDER,
            'subject': 'Hello {{first_name|friend}}',
            'text': 'Hi {{first_name|friend}}',
            'recipients': people(3),
            **body,
        }
        if when is not None:
            payload['send_at'] = when if isinstance(when, str) else when.isoformat()
        return self.create(payload, auth=self.auth)

    def campaign(self, response) -> Campaign:  # noqa: ANN001
        self.assertEqual(response.status_code, 202, response.content)
        return Campaign.objects.get(pk=response.json()['id'])

    def later(self, **delta: float):  # noqa: ANN201
        return timezone.now() + timedelta(**delta)


class CreateTests(ScheduleBase):
    def test_a_campaign_with_a_time_waits_for_it(self) -> None:
        when = self.later(hours=2)
        response = self.schedule(when)
        self.assertEqual(response.json()['status'], 'scheduled')
        self.assertEqual(response.json()['queued'], 3)
        campaign = self.campaign(response)
        self.assertEqual(campaign.status, Campaign.SCHEDULED)
        self.assertEqual(campaign.send_at, when)
        shown = self.api('get', f'/api/v1/campaigns/{campaign.pk}').json()
        self.assertEqual(shown['status'], 'scheduled')
        self.assertEqual(shown['send_at'], when.isoformat(timespec='seconds'))
        self.assertEqual(shown['recipients']['pending'], 3)

    def test_a_campaign_without_a_time_starts_now_as_before(self) -> None:
        campaign = self.campaign(self.schedule(None))
        self.assertEqual((campaign.status, campaign.send_at), (Campaign.SENDING, None))

    def test_a_time_in_another_zone_is_the_same_moment(self) -> None:
        when = self.later(hours=3).replace(microsecond=0)
        local = when.astimezone(timezone.get_fixed_timezone(330))  # +05:30
        campaign = self.campaign(self.schedule(local.isoformat()))
        self.assertEqual(campaign.send_at, when)

    def test_a_time_that_cannot_be_used_is_refused_and_nothing_is_created(self) -> None:
        naive = (timezone.now() + timedelta(hours=2)).replace(tzinfo=None).isoformat()
        for label, when in (
            ('no zone', naive),
            ('past', self.later(hours=-1)),
            ('too soon', self.later(seconds=20)),
            ('too far', self.later(days=400)),
            ('not a time', 'tomorrow morning'),
        ):
            with self.subTest(label):
                self.assertEqual(self.schedule(when).status_code, 422)
        self.assertFalse(Campaign.objects.exists())

    def test_the_status_filter_finds_scheduled_campaigns(self) -> None:
        self.schedule(self.later(hours=1))
        self.schedule(None)
        found = self.api('get', '/api/v1/campaigns?status=scheduled').json()['items']
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['status'], 'scheduled')

    def test_a_retry_with_the_same_idempotency_key_creates_one_campaign(self) -> None:
        body = {
            'from': SENDER,
            'subject': 's',
            'text': 't',
            'recipients': people(1),
            'send_at': self.later(hours=1).isoformat(),
        }
        first = self.create(body, headers={'HTTP_IDEMPOTENCY_KEY': 'k'}, auth=self.auth)
        again = self.create(body, headers={'HTTP_IDEMPOTENCY_KEY': 'k'}, auth=self.auth)
        self.assertEqual(first.json()['id'], again.json()['id'])
        self.assertEqual(Campaign.objects.count(), 1)


class RunnerTests(ScheduleBase):
    def test_nothing_is_sent_before_the_time_and_everything_after_it(self) -> None:
        when = self.later(hours=2)
        campaign = self.campaign(self.schedule(when))
        early = campaign_runner.run(now=when - timedelta(minutes=1))
        self.assertEqual((early.sent, early.started), (0, 0))
        self.assertEqual(len(mail.outbox), 0)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, Campaign.SCHEDULED)
        on_time = campaign_runner.run(now=when + timedelta(seconds=5))
        self.assertEqual((on_time.started, on_time.sent, on_time.completed), (1, 3, 1))
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, Campaign.COMPLETED)
        self.assertEqual(len(mail.outbox), 3)

    def test_the_runner_starts_it_even_when_it_has_no_other_work(self) -> None:
        when = self.later(minutes=5)
        self.campaign(self.schedule(when))
        result = campaign_runner.run(now=when + timedelta(minutes=1))
        self.assertEqual(result.started, 1)
        self.assertNotEqual(result.note, 'nothing is sending')

    def test_two_runs_at_the_time_start_it_once(self) -> None:
        when = self.later(minutes=5)
        self.campaign(self.schedule(when))
        due = when + timedelta(seconds=1)
        self.assertEqual(marketing.start_due(due), (1, 0))
        self.assertEqual(marketing.start_due(due), (0, 0))

    def test_campaigns_due_together_share_the_pace(self) -> None:
        self.configure(pace_per_minute=4)
        when = self.later(minutes=5)
        first = self.campaign(self.schedule(when, recipients=people(10, 'a')))
        second = self.campaign(self.schedule(when, recipients=people(10, 'b')))
        result = campaign_runner.run(now=when + timedelta(seconds=1))
        self.assertEqual((result.started, result.sent), (2, 4))
        self.assertEqual(first.recipients.filter(status='sent').count(), 2)
        self.assertEqual(second.recipients.filter(status='sent').count(), 2)

    def test_the_lists_are_checked_when_it_is_sent_not_when_it_was_created(self) -> None:
        when = self.later(days=3)
        campaign = self.campaign(self.schedule(when))
        MarketingOptOut.objects.create(domain='ifinmail.test', address='p1@example.org')
        result = campaign_runner.run(now=when + timedelta(seconds=1))
        self.assertEqual((result.sent, result.skipped), (2, 1))
        self.assertEqual(campaign.recipients.get(address='p1@example.org').status, 'skipped')

    def test_a_campaign_the_server_missed_by_hours_is_held_not_sent(self) -> None:
        when = self.later(hours=2)
        campaign = self.campaign(self.schedule(when))
        result = campaign_runner.run(now=when + marketing.MAX_LATE + timedelta(minutes=1))
        self.assertEqual((result.started, result.sent, result.paused), (0, 0, 1))
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, Campaign.PAUSED)
        self.assertIn('was due at', campaign.status_detail)
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(marketing.resume(campaign))  # a person looks, and decides to send it
        self.assertEqual(campaign_runner.run().sent, 3)

    def test_a_campaign_a_little_late_is_still_sent(self) -> None:
        when = self.later(hours=2)
        self.campaign(self.schedule(when))
        result = campaign_runner.run(now=when + marketing.MAX_LATE - timedelta(minutes=1))
        self.assertEqual((result.started, result.sent), (1, 3))

    def test_a_scheduled_campaign_is_not_started_while_marketing_is_off(self) -> None:
        from backend.apps.core.plugins.services import InstallationService

        when = self.later(minutes=5)
        campaign = self.campaign(self.schedule(when))
        InstallationService.uninstall('marketing', 'a')
        result = campaign_runner.run(now=when + timedelta(minutes=1))
        self.assertEqual(result.started, 0)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, Campaign.SCHEDULED)


class ControlTests(ScheduleBase):
    def path(self, campaign: Campaign, action: str) -> str:
        return f'/api/v1/campaigns/{campaign.pk}/{action}'

    def test_it_can_be_started_early(self) -> None:
        campaign = self.campaign(self.schedule(self.later(days=2)))
        started = self.api('post', self.path(campaign, 'start'), {}).json()
        self.assertEqual((started['status'], started['send_at']), ('sending', None))
        self.assertEqual(campaign_runner.run().sent, 3)

    def test_starting_a_campaign_that_is_not_scheduled_is_refused(self) -> None:
        campaign = self.campaign(self.schedule(None))
        self.assertEqual(self.api('post', self.path(campaign, 'start'), {}).status_code, 409)

    def test_it_can_be_moved(self) -> None:
        campaign = self.campaign(self.schedule(self.later(days=2)))
        new = self.later(days=5).replace(microsecond=0)
        moved = self.api('post', self.path(campaign, 'schedule'), {'send_at': new.isoformat()})
        self.assertEqual(moved.status_code, 200, moved.content)
        self.assertEqual(moved.json()['send_at'], new.isoformat(timespec='seconds'))
        campaign.refresh_from_db()
        self.assertEqual(campaign.send_at, new)

    def test_a_new_time_is_held_to_the_same_rules(self) -> None:
        campaign = self.campaign(self.schedule(self.later(days=2)))
        for bad in (self.later(hours=-2).isoformat(), self.later(days=500).isoformat()):
            response = self.api('post', self.path(campaign, 'schedule'), {'send_at': bad})
            self.assertEqual(response.status_code, 422)

    def test_only_a_scheduled_campaign_can_be_moved(self) -> None:
        campaign = self.campaign(self.schedule(None))
        response = self.api(
            'post', self.path(campaign, 'schedule'), {'send_at': self.later(days=2).isoformat()}
        )
        self.assertEqual(response.status_code, 409)

    def test_it_can_be_cancelled_and_never_sends(self) -> None:
        when = self.later(minutes=10)
        campaign = self.campaign(self.schedule(when))
        cancelled = self.api('post', self.path(campaign, 'cancel'), {}).json()
        self.assertEqual(cancelled['status'], 'cancelled')
        campaign_runner.run(now=when + timedelta(minutes=1))
        self.assertEqual(len(mail.outbox), 0)

    def test_it_cannot_be_paused_or_resumed_before_it_starts(self) -> None:
        campaign = self.campaign(self.schedule(self.later(days=2)))
        for action in ('pause', 'resume'):
            with self.subTest(action):
                self.assertEqual(self.api('post', self.path(campaign, action), {}).status_code, 409)

    def test_another_keys_campaign_cannot_be_moved_or_started(self) -> None:
        campaign = self.campaign(self.schedule(self.later(days=2)))
        other, _ = self.marketing_key()
        body = {'send_at': self.later(days=3).isoformat()}
        self.assertEqual(
            self.api('post', self.path(campaign, 'schedule'), body, other).status_code, 404
        )
        self.assertEqual(self.api('post', self.path(campaign, 'start'), {}, other).status_code, 404)
