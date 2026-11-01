"""Marketing campaigns: created through the API, sent by the runner at a safe pace.

What these tests pin down, in the order a campaign lives it: merge tags that cannot become markup;
who is left out and why; a key that can send campaigns is not a key that can send everything; the
runner's pace, daily ceiling and warm-up; that two overlapping runs never send a person twice;
that an unsubscribe between creation and sending is honoured; what happens when the relay or the
worker fails; and that unsubscribing from a campaign never stops a receipt.
"""

from __future__ import annotations

from datetime import timedelta
from smtplib import SMTPRecipientsRefused, SMTPServerDisconnected
from unittest.mock import patch

from celery.exceptions import SoftTimeLimitExceeded
from django.core import mail
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from backend.apps.accounts.services.tokens import TokenError, TokenService, key_id
from backend.apps.accounts.tests import test_api_v1 as base
from backend.apps.core.plugins.services import InstallationService
from backend.apps.mail.models import (
    Campaign,
    CampaignRecipient,
    MarketingOptOut,
    Suppression,
)
from backend.apps.mail.services import (
    campaign_runner,
    containment,
    delivery_events,
    marketing,
)
from backend.apps.mail.services.messages import SendRefused

ADDRESS = 'Acme Ltd, 12 High Street, London N1 1AA, UK'
SENDER = 'news@ifinmail.test'
URL = '/api/v1/campaigns'


def policy(**values: dict[str, str]):  # noqa: ANN201
    """Fake some capabilities (Outbound policy's); every other one, Marketing's too, stays real."""
    real = InstallationService.capability_values

    def fake(capability: str) -> dict[str, str]:
        return dict(values[capability]) if capability in values else real(capability)

    return patch.object(InstallationService, 'capability_values', side_effect=fake)


def people(n: int, prefix: str = 'p') -> list[dict]:
    return [
        {'email': f'{prefix}{i}@example.org', 'merge': {'first_name': f'Person{i}'}}
        for i in range(n)
    ]


class MergeTagTests(SimpleTestCase):
    def test_tags_are_found_with_their_fallbacks(self) -> None:
        found = marketing.tags_in('Hi {{ first_name }}', '{{city|your town}} {{email}}')
        self.assertEqual(found, [('first_name', None), ('city', 'your town'), ('email', None)])

    def test_values_fill_in_and_a_fallback_covers_a_missing_one(self) -> None:
        self.assertEqual(
            marketing.render('Hi {{first_name|friend}}', {'first_name': 'Ana'}, escape=False),
            'Hi Ana',
        )
        self.assertEqual(
            marketing.render('Hi {{first_name|friend}}', {}, escape=False), 'Hi friend'
        )
        self.assertEqual(
            marketing.render('Hi {{first_name|friend}}', {'first_name': ''}, escape=False),
            'Hi friend',
        )

    def test_a_missing_value_without_a_fallback_is_an_error_not_an_empty_greeting(self) -> None:
        with self.assertRaises(marketing.MissingValue) as caught:
            marketing.render('Hi {{first_name}},', {}, escape=False)
        self.assertEqual(caught.exception.name, 'first_name')

    def test_a_value_cannot_become_markup_in_html(self) -> None:
        out = marketing.render('<p>{{name}}</p>', {'name': '<script>x</script> & "q"'}, escape=True)
        self.assertEqual(out, '<p>&lt;script&gt;x&lt;/script&gt; &amp; &quot;q&quot;</p>')
        self.assertEqual(marketing.render('{{name}}', {'name': '<b>'}, escape=False), '<b>')

    def test_text_that_only_looks_like_a_tag_is_left_alone(self) -> None:
        for text in ('{{ }}', '{{First}}', '{{1abc}}', '{ {a} }', '{{a b}}'):
            with self.subTest(text=text):
                self.assertEqual(marketing.render(text, {'a': 'X'}, escape=False), text)

    def test_merge_values_are_checked(self) -> None:
        clean = marketing._clean_merge
        self.assertEqual(clean({'First_Name': ' Ana ', 'n': 3}), {'first_name': 'Ana', 'n': '3'})
        self.assertEqual(clean(None), {})
        self.assertIsNone(clean({'email': 'x'}))  # built in: not the sender's to set
        self.assertIsNone(clean({'unsubscribe_url': 'x'}))
        self.assertIsNone(clean({'bad name': 'x'}))
        self.assertIsNone(clean({'a': 'x' * (marketing.MAX_MERGE_VALUE + 1)}))
        self.assertIsNone(clean({f'k{i}': 'x' for i in range(marketing.MAX_MERGE_KEYS + 1)}))
        self.assertIsNone(clean({'a': ['nested']}))
        self.assertIsNone(clean('not a mapping'))


@override_settings(CACHES=base.LOCMEM)
class MarketingBase(base.ApiBase):
    def setUp(self) -> None:
        super().setUp()
        self.configure()

    def configure(self, **settings: object) -> None:
        values = {'postal_address': ADDRESS, 'warmup': False, 'daily_ceiling': 100000, **settings}
        if InstallationService.get('marketing') is None:
            InstallationService.install('marketing', values, 'a')
        else:
            InstallationService.configure('marketing', values, 'a')

    def marketing_key(
        self, senders: list[str] | None = None, scopes: list[str] | None = None, **kw
    ):
        row, token = TokenService.create(
            self.owner,
            'newsletter',
            scopes or ['marketing.send'],
            expires_in_days=30,
            allowed_senders=senders if senders is not None else [SENDER],
            **kw,
        )
        return {'key': key_id(row.prefix), 'secret': token.split('.', 2)[2]}, row

    def create(self, body: dict | None = None, *, headers: dict | None = None, auth=None):
        auth = auth or self.marketing_key()[0]
        body = body or {
            'from': SENDER,
            'subject': 'Hello {{first_name}}',
            'text': 'Hi {{first_name}}',
            'recipients': people(3),
        }
        return self.call(
            'post', URL, key=auth['key'], secret=auth['secret'], body=body, extra=headers
        )

    def campaign_from(self, n: int = 5, **request: object) -> marketing.Created:
        return marketing.create(
            marketing.CampaignRequest(
                sender=SENDER,
                subject=request.pop('subject', 'Hello {{first_name|friend}}'),  # type: ignore[arg-type]
                text=request.pop('text', 'Hi {{first_name|friend}}'),  # type: ignore[arg-type]
                html=request.pop('html', None),  # type: ignore[arg-type]
                recipients=tuple(
                    marketing.RecipientIn(f'p{i}@example.org', {'first_name': f'P{i}'})
                    for i in range(n)
                ),
                **request,  # type: ignore[arg-type]
            ),
            marketing.CampaignKey(prefix='abc123', name='newsletter', allowed_senders=(SENDER,)),
        )

    def statuses(self, campaign: Campaign) -> dict[str, int]:
        return marketing.counts(campaign)


class KeyAndPluginTests(MarketingBase):
    def test_marketing_is_installed_by_default_and_off_until_configured(self) -> None:
        InstallationService.uninstall('marketing', 'a')
        self.assertFalse(marketing.settings().enabled)  # nothing installed: no campaigns
        InstallationService.reconcile()
        cfg = marketing.settings()
        self.assertTrue(cfg.enabled)
        self.assertEqual(
            (cfg.pace_per_minute, cfg.daily_ceiling, cfg.max_recipients), (60, 2000, 10000)
        )
        self.assertTrue(cfg.warmup)
        self.assertEqual(cfg.postal_address, '')  # no postal address, so no campaign yet
        self.assertEqual(self.create().status_code, 409)

    def test_the_postal_address_is_validated(self) -> None:
        from backend.apps.core.plugins.services.lifecycle import PluginError

        for bad in ('x', '<b>Acme</b>, 1 High St'):
            with self.subTest(address=bad), self.assertRaises(PluginError):
                InstallationService.configure('marketing', {'postal_address': bad}, 'a')

    def test_a_key_that_runs_campaigns_must_name_its_senders(self) -> None:
        with self.assertRaises(TokenError):
            TokenService.create(self.owner, 'k', ['marketing.send'], expires_in_days=30)
        _, row = self.marketing_key(['*@ifinmail.test'])
        self.assertEqual(row.allowed_senders, ['*@ifinmail.test'])

    def test_a_transactional_key_cannot_run_a_campaign_and_a_marketing_key_cannot_send_mail(
        self,
    ) -> None:
        sender_row, token = TokenService.create(
            self.owner, 'mailer', ['mail.send'], expires_in_days=30, allowed_senders=[SENDER]
        )
        auth = {'key': key_id(sender_row.prefix), 'secret': token.split('.', 2)[2]}
        self.assertEqual(self.create(auth=auth).status_code, 403)
        marketing_auth = self.marketing_key()[0]
        response = self.call(
            'post',
            '/api/v1/messages',
            key=marketing_auth['key'],
            secret=marketing_auth['secret'],
            body={'from': SENDER, 'to': ['a@example.org'], 'subject': 's', 'text': 't'},
        )
        self.assertEqual(response.status_code, 403)

    def test_the_role_that_holds_every_permission_holds_the_new_one(self) -> None:
        from backend.apps.accounts.services.roles import RoleService
        from backend.apps.accounts.types.permissions import TOKEN_SCOPES

        self.assertIn('marketing.send', TOKEN_SCOPES)
        self.assertTrue(RoleService.has_perm(self.owner, 'marketing.send'))


class CreateTests(MarketingBase):
    def test_a_campaign_is_created_and_nothing_is_sent_in_the_call(self) -> None:
        response = self.create()
        self.assertEqual(response.status_code, 202, response.content)
        body = response.json()
        self.assertEqual((body['status'], body['queued'], body['skipped']), ('sending', 3, {}))
        self.assertEqual(mail.outbox, [])
        campaign = Campaign.objects.get(pk=body['id'])
        self.assertEqual(self.statuses(campaign)['pending'], 3)

    def test_the_audit_trail_names_the_key_and_never_the_content(self) -> None:
        from backend.apps.core.platform.models import AuditEvent

        self.create(
            {'from': SENDER, 'subject': 'Secret sale', 'text': 'x', 'recipients': people(2)}
        )
        event = AuditEvent.objects.get(action='api_campaign_created')
        self.assertIn('api:ifm_', event.user)
        self.assertNotIn('Secret sale', event.detail)

    def test_refusals(self) -> None:
        from backend.apps.domains.models import Domain

        Domain.objects.create(name='gone.example')
        removed = self.marketing_key(['news@gone.example'])[0]
        Domain.objects.filter(name='gone.example').delete()  # the key outlived its domain
        narrow = self.marketing_key()[0]
        cases = [
            ('a sender the key may not use', {'from': 'other@ifinmail.test'}, narrow, 403),
            ('a domain no longer hosted here', {'from': 'news@gone.example'}, removed, 403),
            ('no body', {'text': None, 'html': None}, narrow, 422),
            ('a subject with a line break', {'subject': 'a\nb'}, narrow, 422),
        ]
        for name, change, auth, status in cases:
            body = {
                'from': SENDER,
                'subject': 'Hello',
                'text': 'Hi',
                'recipients': people(2),
                **change,
            }
            with self.subTest(case=name):
                self.assertEqual(self.create(body, auth=auth).status_code, status)

    def test_a_sandbox_key_cannot_run_a_campaign(self) -> None:
        auth, _ = self.marketing_key(sandbox=True)
        self.assertEqual(self.create(auth=auth).status_code, 403)

    def test_a_paused_sender_cannot_start_a_campaign(self) -> None:
        with patch.object(containment, 'paused', return_value={SENDER: {'reason': 'flood'}}):
            self.assertEqual(self.create().status_code, 403)

    def test_the_recipient_limit_is_the_plugins(self) -> None:
        self.configure(max_recipients=3)
        self.assertEqual(self.create().status_code, 202)
        body = {'from': SENDER, 'subject': 'Hi', 'text': 'x', 'recipients': people(4)}
        response = self.create(body)
        self.assertEqual(response.status_code, 422)
        self.assertIn('at most 3', response.json()['detail'])

    def test_a_tag_nobody_has_a_value_for_is_a_typo_not_a_campaign(self) -> None:
        body = {
            'from': SENDER,
            'subject': 'Hi {{frist_name}}',
            'text': 'x',
            'recipients': people(2),
        }
        response = self.create(body)
        self.assertEqual(response.status_code, 422)
        self.assertIn('{{frist_name}}', response.json()['detail'])
        self.assertEqual(Campaign.objects.count(), 0)

    def test_a_tag_with_a_fallback_needs_no_values(self) -> None:
        body = {
            'from': SENDER,
            'subject': 'Hi {{first_name|friend}}',
            'text': 'x',
            'recipients': [{'email': 'a@example.org'}],
        }
        self.assertEqual(self.create(body).status_code, 202)

    def test_someone_missing_a_value_is_skipped_not_greeted_with_a_blank(self) -> None:
        body = {
            'from': SENDER,
            'subject': 'Hi {{first_name}}',
            'text': 'x',
            'recipients': [
                {'email': 'a@example.org', 'merge': {'first_name': 'Ana'}},
                {'email': 'b@example.org'},
            ],
        }
        response = self.create(body)
        self.assertEqual(response.json()['skipped'], {'missing': 1})
        row = CampaignRecipient.objects.get(address='b@example.org')
        self.assertEqual((row.status, row.detail), ('skipped', 'missing: first_name'))

    def test_who_is_left_out_and_why(self) -> None:
        Suppression.objects.create(
            domain='ifinmail.test', address='gone@example.org', reason='bounced'
        )
        MarketingOptOut.objects.create(domain='ifinmail.test', address='no@example.org')
        recipients = [
            *people(2),
            {'email': 'gone@example.org', 'merge': {'first_name': 'G'}},
            {'email': 'NO@example.org', 'merge': {'first_name': 'N'}},
            {'email': 'blocked@spam.example', 'merge': {'first_name': 'B'}},
            {'email': 'not an address', 'merge': {'first_name': 'X'}},
            {'email': 'p0@example.org', 'merge': {'first_name': 'Dup'}},
            {'email': 'bad@example.org', 'merge': {'email': 'not allowed'}},
        ]
        body = {
            'from': SENDER,
            'subject': 'Hi {{first_name}}',
            'text': 'x',
            'recipients': recipients,
        }
        with policy(**{'sending.blocked_destinations': {'domains': 'spam.example'}}):
            response = self.create(body)
        self.assertEqual(response.status_code, 202, response.content)
        body = response.json()
        self.assertEqual(body['queued'], 2)
        self.assertEqual(
            body['skipped'],
            {'suppressed': 1, 'opted_out': 1, 'blocked': 1, 'invalid': 2, 'duplicate': 1},
        )

    def test_when_everyone_is_left_out_nothing_is_created(self) -> None:
        for p in people(2):
            MarketingOptOut.objects.create(domain='ifinmail.test', address=p['email'])
        response = self.create(
            {'from': SENDER, 'subject': 'x', 'text': 'x', 'recipients': people(2)}
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn('Nobody is left', response.json()['detail'])
        self.assertEqual(Campaign.objects.count(), 0)

    def test_a_retry_with_the_same_idempotency_key_creates_one_campaign(self) -> None:
        auth = self.marketing_key()[0]
        first = self.create(auth=auth, headers={'HTTP_IDEMPOTENCY_KEY': 'spring-2026'})
        again = self.create(auth=auth, headers={'HTTP_IDEMPOTENCY_KEY': 'spring-2026'})
        self.assertEqual(first.json()['id'], again.json()['id'])
        self.assertEqual(Campaign.objects.count(), 1)
        other = self.create(
            {'from': SENDER, 'subject': 'Different', 'text': 'x', 'recipients': people(2)},
            auth=auth,
            headers={'HTTP_IDEMPOTENCY_KEY': 'spring-2026'},
        )
        self.assertEqual(other.status_code, 422)

    def test_a_key_paused_for_bounces_cannot_start_a_campaign(self) -> None:
        InstallationService.install('sender-compliance', {}, 'a')
        auth, row = self.marketing_key()
        cache.set(f'compliance:paused:{row.prefix}', {'rate': 12.0, 'total': 80}, None)
        self.assertEqual(self.create(auth=auth).status_code, 403)


class ReadAndControlTests(MarketingBase):
    def test_progress_and_the_page_shape(self) -> None:
        auth = self.marketing_key()[0]
        created = self.create(auth=auth).json()
        detail = self.call('get', f'{URL}/{created["id"]}', key=auth['key'], secret=auth['secret'])
        self.assertEqual(detail.status_code, 200, detail.content)
        body = detail.json()
        self.assertEqual(body['status'], 'sending')
        self.assertEqual(body['from'], SENDER)
        self.assertEqual(
            body['recipients'], {'pending': 3, 'sending': 0, 'sent': 0, 'failed': 0, 'skipped': 0}
        )
        listing = self.call('get', URL, key=auth['key'], secret=auth['secret']).json()
        self.assertEqual(listing['count'], 1)
        self.assertEqual(listing['items'][0]['id'], created['id'])

    def test_a_key_sees_only_its_own_campaigns_but_mail_manage_sees_all(self) -> None:
        mine, theirs = self.marketing_key()[0], self.marketing_key()[0]
        manager = self.marketing_key(scopes=['marketing.send', 'mail.manage'])[0]
        campaign_id = self.create(auth=mine).json()['id']
        path = f'{URL}/{campaign_id}'
        self.assertEqual(
            self.call('get', path, key=theirs['key'], secret=theirs['secret']).status_code, 404
        )
        self.assertEqual(
            self.call('get', URL, key=theirs['key'], secret=theirs['secret']).json()['count'], 0
        )
        self.assertEqual(
            self.call('get', path, key=manager['key'], secret=manager['secret']).status_code, 200
        )
        self.assertEqual(
            self.call('get', URL, key=manager['key'], secret=manager['secret']).json()['count'], 1
        )
        not_a_uuid = f'{URL}/not-a-uuid'
        self.assertEqual(
            self.call('get', not_a_uuid, key=mine['key'], secret=mine['secret']).status_code, 404
        )

    def test_recipients_can_be_listed_by_status(self) -> None:
        auth = self.marketing_key()[0]
        MarketingOptOut.objects.create(domain='ifinmail.test', address='p0@example.org')
        created = self.create(auth=auth).json()
        everything = self.call(
            'get', f'{URL}/{created["id"]}/recipients', key=auth['key'], secret=auth['secret']
        )
        self.assertEqual(everything.json()['count'], 3)
        skipped = self.call(
            'get',
            f'{URL}/{created["id"]}/recipients?status=skipped',
            key=auth['key'],
            secret=auth['secret'],
        ).json()
        self.assertEqual(
            [(r['email'], r['status']) for r in skipped['items']], [('p0@example.org', 'skipped')]
        )
        self.assertTrue(skipped['items'][0]['detail'].startswith('opted_out'))

    def test_pause_resume_and_cancel(self) -> None:
        auth = self.marketing_key()[0]
        cid = self.create(auth=auth).json()['id']

        def act(action: str):  # noqa: ANN202
            return self.call(
                'post', f'{URL}/{cid}/{action}', key=auth['key'], secret=auth['secret'], body={}
            )

        self.assertEqual(act('resume').status_code, 409)  # not paused
        self.assertEqual(act('pause').json()['status'], 'paused')
        self.assertEqual(act('pause').status_code, 409)
        self.assertEqual(act('resume').json()['status'], 'sending')
        cancelled = act('cancel').json()
        self.assertEqual(cancelled['status'], 'cancelled')
        self.assertIsNotNone(cancelled['finished_at'])
        self.assertEqual(act('cancel').status_code, 409)  # already over
        self.assertEqual(act('resume').status_code, 409)

    def test_opt_outs_can_be_added_listed_and_only_a_manager_can_remove_one(self) -> None:
        auth = self.marketing_key()[0]
        body = {'address': 'Ana@Example.org', 'domain': 'ifinmail.test'}
        added = self.call(
            'post', '/api/v1/marketing/opt-outs', key=auth['key'], secret=auth['secret'], body=body
        )
        self.assertEqual(added.status_code, 201, added.content)
        self.assertEqual(
            (added.json()['address'], added.json()['source']), ('ana@example.org', 'api')
        )
        again = self.call(
            'post', '/api/v1/marketing/opt-outs', key=auth['key'], secret=auth['secret'], body=body
        )
        self.assertEqual(again.status_code, 409)
        elsewhere = {'address': 'a@example.org', 'domain': 'other.example'}
        refused = self.call(
            'post',
            '/api/v1/marketing/opt-outs',
            key=auth['key'],
            secret=auth['secret'],
            body=elsewhere,
        )
        self.assertEqual(refused.status_code, 403)
        listing = self.call(
            'get', '/api/v1/marketing/opt-outs', key=auth['key'], secret=auth['secret']
        ).json()
        self.assertEqual(listing['count'], 1)
        path = '/api/v1/marketing/opt-outs/ifinmail.test/ana@example.org'
        self.assertEqual(
            self.call('delete', path, key=auth['key'], secret=auth['secret']).status_code, 403
        )
        self.assertEqual(self.delete(path).status_code, 204)  # mail.manage
        self.assertEqual(self.delete(path).status_code, 404)


class RunnerTests(MarketingBase):
    def run_once(self, **kw):  # noqa: ANN201
        return campaign_runner.run(**kw)

    def test_each_person_gets_their_own_email_with_a_footer_and_the_unsubscribe_headers(
        self,
    ) -> None:
        self.campaign_from(3, html='<html><body><p>Hi {{first_name|friend}}</p></body></html>')
        result = self.run_once()
        self.assertEqual((result.sent, result.completed), (3, 1))
        self.assertEqual(len(mail.outbox), 3)
        first = mail.outbox[0]
        self.assertEqual(first.to, ['p0@example.org'])  # one recipient per message
        self.assertEqual(first.from_email, SENDER)
        self.assertEqual(first.subject, 'Hello P0')
        self.assertIn('Hi P0', first.body)
        self.assertIn(ADDRESS, first.body)
        link = first.extra_headers['List-Unsubscribe'].strip('<>')
        self.assertIn('/unsubscribe/m/', link)
        self.assertEqual(first.extra_headers['List-Unsubscribe-Post'], 'List-Unsubscribe=One-Click')
        self.assertEqual(first.extra_headers['Precedence'], 'bulk')
        self.assertIn(link, first.body)
        html = first.alternatives[0].content
        self.assertIn('Hi P0', html)
        self.assertIn(ADDRESS, html)
        self.assertLess(html.index(ADDRESS), html.index('</body>'))  # the footer is inside the page
        links = {m.extra_headers['List-Unsubscribe'] for m in mail.outbox}
        self.assertEqual(len(links), 3)  # a personal link for each person

    def test_a_person_value_cannot_inject_markup_into_the_email(self) -> None:
        marketing.create(
            marketing.CampaignRequest(
                sender=SENDER,
                subject='Hi',
                text='plain {{n}}',
                html='<p>{{n}}</p>',
                recipients=(
                    marketing.RecipientIn('a@example.org', {'n': '<img src=x onerror=1>'}),
                ),
            ),
            marketing.CampaignKey(prefix='abc123', name='n', allowed_senders=(SENDER,)),
        )
        self.run_once()
        message = mail.outbox[0]
        self.assertIn('&lt;img', message.alternatives[0].content)
        self.assertNotIn('<img', message.alternatives[0].content)
        self.assertIn('<img src=x onerror=1>', message.body)  # plain text stays plain

    def test_a_campaign_is_not_held_to_the_transactional_limits(self) -> None:
        self.campaign_from(6)
        with (
            policy(**{'sending.rate_limit': {'per_minute': '1', 'per_day': '1'}}),
            patch.object(containment, 'record_send') as record,
        ):
            result = self.run_once()
        self.assertEqual(result.sent, 6)  # not one a minute, and not stopped at the daily limit
        record.assert_not_called()  # a newsletter must not trip containment's hourly pause

    def test_the_pace_per_minute_is_the_budget_and_the_campaign_completes(self) -> None:
        self.configure(pace_per_minute=2)
        created = self.campaign_from(5)
        start = timezone.now()
        sent = [self.run_once(now=start + timedelta(minutes=k)).sent for k in range(4)]
        self.assertEqual(sent, [2, 2, 1, 0])
        campaign = Campaign.objects.get(pk=created.campaign.pk)
        self.assertEqual(campaign.status, 'completed')
        self.assertIsNotNone(campaign.finished_at)
        self.assertEqual(len(mail.outbox), 5)

    def test_a_second_run_in_the_same_minute_finds_the_pace_already_used(self) -> None:
        # Seen on a real worker: three extra runs fired in one minute each got a fresh budget and
        # the relay received 200 emails against a pace of 100.
        self.configure(pace_per_minute=3)
        created = self.campaign_from(10)
        now = timezone.now().replace(second=30)
        first = self.run_once(now=now)
        again = [self.run_once(now=now + timedelta(seconds=s)) for s in (5, 10, 20)]
        self.assertEqual(first.sent, 3)
        self.assertEqual([r.sent for r in again], [0, 0, 0])
        self.assertEqual(again[0].note, "this minute's pace is used up")
        self.assertEqual(self.statuses(created.campaign)['sent'], 3)
        self.assertEqual(self.run_once(now=now + timedelta(minutes=1)).sent, 3)  # the next minute

    def test_a_run_that_only_partly_used_the_minute_leaves_the_rest_to_the_next_run(self) -> None:
        self.configure(pace_per_minute=5)
        created = self.campaign_from(3)  # fewer than the pace
        self.assertEqual(self.run_once().sent, 3)
        self.campaign_from(3)  # a second campaign arrives in the same minute
        self.assertEqual(self.run_once().sent, 2)  # only what is left of the 5
        self.assertEqual(self.statuses(created.campaign)['sent'], 3)

    def test_the_daily_ceiling_stops_the_day(self) -> None:
        self.configure(pace_per_minute=100, daily_ceiling=4)
        created = self.campaign_from(6)
        start = timezone.now()
        self.assertEqual(self.run_once(now=start).sent, 4)
        later = self.run_once(now=start + timedelta(minutes=1))
        self.assertEqual((later.sent, later.note), (0, "today's ceiling is reached"))
        self.assertEqual(self.statuses(created.campaign)['pending'], 2)
        CampaignRecipient.objects.filter(status='sent').update(
            sent_at=timezone.now() - timedelta(days=1)
        )
        self.assertEqual(self.run_once(now=start + timedelta(minutes=2)).sent, 2)  # a new day

    def test_warm_up_starts_low_and_grows_by_half_each_day(self) -> None:
        self.configure(warmup=True, warmup_start=200, daily_ceiling=1000)
        cfg = marketing.settings()
        now = timezone.now()
        self.assertEqual(campaign_runner.ceiling_today(cfg, now), 200)  # nothing sent yet: day 0
        created = self.campaign_from(1)
        self.run_once()
        for days, expected in ((0, 200), (1, 300), (2, 450), (3, 675), (5, 1000), (30, 1000)):
            CampaignRecipient.objects.filter(campaign=created.campaign, status='sent').update(
                sent_at=now - timedelta(days=days)
            )
            with self.subTest(days_since_first_send=days):
                self.assertEqual(campaign_runner.ceiling_today(cfg, now), expected)

    def test_the_budget_is_shared_between_campaigns(self) -> None:
        self.configure(pace_per_minute=4)
        big, small = self.campaign_from(10), self.campaign_from(10)
        self.run_once()
        self.assertEqual(self.statuses(big.campaign)['sent'], 2)
        self.assertEqual(self.statuses(small.campaign)['sent'], 2)

    def test_two_overlapping_runs_never_send_a_person_twice(self) -> None:
        self.campaign_from(4)
        inner: list[campaign_runner.RunResult] = []
        real_send = mail.EmailMultiAlternatives.send

        def send_and_overlap(message, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
            if not inner:
                inner.append(campaign_runner.run())  # another worker starts mid-run
            return real_send(message, *args, **kwargs)

        with patch.object(mail.EmailMultiAlternatives, 'send', send_and_overlap):
            self.run_once()
        self.assertEqual((inner[0].sent, inner[0].note), (0, 'another run is in progress'))
        recipients = sorted(m.to[0] for m in mail.outbox)
        self.assertEqual(recipients, sorted(set(recipients)))
        self.assertEqual(len(recipients), 4)

    def test_recipients_already_claimed_by_another_run_are_not_taken(self) -> None:
        created = self.campaign_from(3)
        CampaignRecipient.objects.filter(
            campaign=created.campaign, address='p0@example.org'
        ).update(status='sending', claim_token='other', claimed_at=timezone.now())
        self.run_once()
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ['p1@example.org', 'p2@example.org'])

    def test_an_unsubscribe_between_creation_and_sending_is_honoured(self) -> None:
        created = self.campaign_from(3)
        marketing.opt_out('ifinmail.test', 'p1@example.org')
        Suppression.objects.create(
            domain='ifinmail.test', address='p2@example.org', reason='bounced'
        )
        result = self.run_once()
        self.assertEqual((result.sent, result.skipped), (1, 2))
        self.assertEqual([m.to[0] for m in mail.outbox], ['p0@example.org'])
        rows = {r.address: r for r in created.campaign.recipients.all()}
        self.assertTrue(rows['p1@example.org'].detail.startswith('opted_out'))
        self.assertTrue(rows['p2@example.org'].detail.startswith('suppressed'))

    def test_a_cancelled_or_paused_campaign_sends_nothing(self) -> None:
        paused, cancelled = self.campaign_from(2), self.campaign_from(2)
        marketing.pause(paused.campaign)
        marketing.cancel(cancelled.campaign)
        self.assertEqual(self.run_once().sent, 0)
        self.assertEqual(mail.outbox, [])

    def test_nothing_happens_when_marketing_is_off_or_has_no_address(self) -> None:
        self.campaign_from(2)
        self.configure(postal_address='')
        self.assertEqual(self.run_once().sent, 0)
        InstallationService.uninstall('marketing', 'a')
        self.assertEqual(self.run_once().sent, 0)
        self.assertEqual(mail.outbox, [])


class RunnerSafetyTests(MarketingBase):
    def test_a_paused_sender_pauses_the_campaign_and_says_why(self) -> None:
        created = self.campaign_from(3)
        with patch.object(containment, 'paused', return_value={SENDER: {'reason': 'flood'}}):
            result = campaign_runner.run()
        self.assertEqual((result.sent, result.paused), (0, 1))
        campaign = Campaign.objects.get(pk=created.campaign.pk)
        self.assertEqual(campaign.status, 'paused')
        self.assertIn('paused for news@ifinmail.test', campaign.status_detail)
        self.assertEqual(mail.outbox, [])

    def test_a_campaign_that_bounces_too_much_stops_itself(self) -> None:
        created = self.campaign_from(6)
        with patch.object(marketing, 'GUARD_MIN_SENT', 2):
            self.configure(pace_per_minute=2)
            campaign_runner.run()
            cache.set(f'marketing:bounced:{created.campaign.pk}', 1, None)  # 1 of 2: 50%
            result = campaign_runner.run()
        self.assertEqual((result.sent, result.paused), (0, 1))
        campaign = Campaign.objects.get(pk=created.campaign.pk)
        self.assertEqual(campaign.status, 'paused')
        self.assertIn('50.0% of the 2 emails', campaign.status_detail)
        self.assertEqual(len(mail.outbox), 2)

    def test_a_key_paused_by_the_bounce_guard_stops_its_campaigns(self) -> None:
        InstallationService.install('sender-compliance', {}, 'a')
        created = self.campaign_from(3)
        cache.set('compliance:paused:abc123', {'rate': 9.0, 'total': 120}, None)
        result = campaign_runner.run()
        self.assertEqual(result.paused, 1)
        self.assertIn('9.0%', Campaign.objects.get(pk=created.campaign.pk).status_detail)

    def test_a_relay_that_refuses_the_connection_loses_nobody(self) -> None:
        created = self.campaign_from(3)
        with patch(
            'django.core.mail.backends.locmem.EmailBackend.open', side_effect=OSError('down')
        ):
            result = campaign_runner.run()
        self.assertEqual((result.sent, result.note), (0, 'the relay did not accept a connection'))
        self.assertEqual(self.statuses(created.campaign)['pending'], 3)
        self.assertEqual(campaign_runner.run().sent, 3)  # the next run sends them

    def test_a_relay_that_drops_mid_run_puts_the_rest_back_without_repeating_anyone(self) -> None:
        created = self.campaign_from(5)
        calls = {'n': 0}
        real_send = mail.EmailMultiAlternatives.send

        def drops_on_the_third(message, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
            calls['n'] += 1
            if calls['n'] == 3:
                raise SMTPServerDisconnected('connection lost')
            return real_send(message, *args, **kwargs)

        with patch.object(mail.EmailMultiAlternatives, 'send', drops_on_the_third):
            result = campaign_runner.run()
        self.assertEqual(result.sent, 2)
        counts = self.statuses(created.campaign)
        self.assertEqual((counts['sent'], counts['pending'], counts['sending']), (2, 3, 0))
        self.assertEqual(campaign_runner.run().sent, 3)
        recipients = [m.to[0] for m in mail.outbox]
        self.assertEqual(len(recipients), len(set(recipients)))  # nobody twice

    def test_a_refused_recipient_fails_alone_and_the_campaign_goes_on(self) -> None:
        created = self.campaign_from(3)
        real_send = mail.EmailMultiAlternatives.send

        def refuses_one(message, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
            if message.to == ['p1@example.org']:
                raise SMTPRecipientsRefused({'p1@example.org': (550, b'no such user')})
            return real_send(message, *args, **kwargs)

        with patch.object(mail.EmailMultiAlternatives, 'send', refuses_one):
            result = campaign_runner.run()
        self.assertEqual((result.sent, result.failed), (2, 1))
        row = created.campaign.recipients.get(address='p1@example.org')
        self.assertEqual(row.status, 'failed')
        self.assertTrue(row.detail.startswith('refused'))
        self.assertEqual(Campaign.objects.get(pk=created.campaign.pk).status, 'completed')

    def refusing(self, every: int = 1):  # noqa: ANN202
        """A relay that refuses the emails whose position is a multiple of ``every``."""
        from smtplib import SMTPDataError

        real_send = mail.EmailMultiAlternatives.send
        calls = {'n': 0}

        def send(message, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
            calls['n'] += 1
            if calls['n'] % every == 0:
                raise SMTPDataError(500, b'Error: relay misconfigured')
            return real_send(message, *args, **kwargs)

        return patch.object(mail.EmailMultiAlternatives, 'send', send)

    def test_a_relay_that_refuses_everything_pauses_the_campaign_with_the_list_intact(self) -> None:
        created = self.campaign_from(30)
        with self.refusing():
            result = campaign_runner.run()
        counts = self.statuses(created.campaign)
        self.assertEqual((counts['failed'], counts['pending'], counts['sent']), (20, 10, 0))
        self.assertEqual(result.paused, 1)
        campaign = Campaign.objects.get(pk=created.campaign.pk)
        self.assertEqual(campaign.status, 'paused')
        self.assertIn('refused 20 emails in a row', campaign.status_detail)
        self.assertEqual(campaign_runner.run().sent, 0)  # paused: nothing more goes out
        marketing.resume(campaign)  # the owner fixed the relay
        self.assertEqual(campaign_runner.run().sent, 10)
        self.assertEqual(Campaign.objects.get(pk=created.campaign.pk).status, 'completed')

    def test_the_streak_is_counted_across_runs_when_the_pace_is_low(self) -> None:
        self.configure(pace_per_minute=5)
        created = self.campaign_from(30)
        with self.refusing():
            outcomes = [campaign_runner.run().paused for _ in range(4)]
        self.assertEqual(outcomes, [0, 0, 0, 1])  # 5, 10, 15 refused: fine; the 20th pauses it
        self.assertEqual(Campaign.objects.get(pk=created.campaign.pk).status, 'paused')
        self.assertEqual(self.statuses(created.campaign)['pending'], 10)

    def test_a_success_resets_the_streak(self) -> None:
        created = self.campaign_from(60)
        with self.refusing(every=2):  # every other email is refused: never 20 in a row
            campaign_runner.run()
        self.assertEqual(Campaign.objects.get(pk=created.campaign.pk).status, 'completed')
        counts = self.statuses(created.campaign)
        self.assertEqual((counts['sent'], counts['failed']), (30, 30))

    def test_people_missing_a_value_do_not_count_against_the_relay(self) -> None:
        created = self.campaign_from(25)
        CampaignRecipient.objects.filter(campaign=created.campaign).update(merge={})
        # the subject has a fallback, so nothing is missing; remove it from the stored subject
        Campaign.objects.filter(pk=created.campaign.pk).update(subject='Hi {{first_name}}')
        result = campaign_runner.run()
        self.assertEqual((result.failed, result.paused), (25, 0))
        self.assertEqual(Campaign.objects.get(pk=created.campaign.pk).status, 'completed')

    def test_a_worker_stopped_mid_send_never_repeats_the_one_in_flight(self) -> None:
        created = self.campaign_from(4)
        calls = {'n': 0}
        real_send = mail.EmailMultiAlternatives.send

        def stopped_on_the_second(message, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
            calls['n'] += 1
            if calls['n'] == 2:
                raise SoftTimeLimitExceeded()
            return real_send(message, *args, **kwargs)

        with (
            patch.object(mail.EmailMultiAlternatives, 'send', stopped_on_the_second),
            self.assertRaises(SoftTimeLimitExceeded),
        ):
            campaign_runner.run()
        counts = self.statuses(created.campaign)
        # one sent; the one in flight stays claimed (we cannot know if it went); two are released
        self.assertEqual((counts['sent'], counts['sending'], counts['pending']), (1, 1, 2))
        later = campaign_runner.run(
            now=timezone.now() + campaign_runner.STALE_CLAIM + timedelta(seconds=1)
        )
        self.assertEqual(later.sent, 2)
        failed = created.campaign.recipients.get(status='failed')
        self.assertEqual(failed.detail, 'interrupted: may or may not have been sent')
        recipients = [m.to[0] for m in mail.outbox]
        self.assertEqual(len(recipients), len(set(recipients)))

    def test_a_hard_stop_leaves_at_most_one_recipient_in_doubt(self) -> None:
        # Seen on a real worker killed with SIGKILL: claiming the whole batch up front left all
        # 70 unsent recipients of a batch of 100 in doubt. Each is now claimed right before its
        # own email, so only the one in flight is.
        class HardStop(BaseException):  # a process that is gone: nothing catches it
            pass

        created = self.campaign_from(50)
        calls = {'n': 0}
        real_send = mail.EmailMultiAlternatives.send

        def dies_on_the_tenth(message, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
            calls['n'] += 1
            if calls['n'] == 10:
                raise HardStop()
            return real_send(message, *args, **kwargs)

        with (
            patch.object(mail.EmailMultiAlternatives, 'send', dies_on_the_tenth),
            self.assertRaises(HardStop),
        ):
            campaign_runner.run()
        counts = self.statuses(created.campaign)
        self.assertEqual((counts['sent'], counts['sending'], counts['pending']), (9, 1, 40))
        cache.delete(campaign_runner.LOCK_KEY)  # a dead process never released its lock
        later = campaign_runner.run(
            now=timezone.now() + campaign_runner.STALE_CLAIM + timedelta(minutes=1)
        )
        self.assertEqual(later.sent, 40)  # everyone else goes out on the next run
        failed = list(created.campaign.recipients.filter(status='failed'))
        self.assertEqual([r.detail for r in failed], ['interrupted: may or may not have been sent'])
        recipients = [m.to[0] for m in mail.outbox]
        self.assertEqual(len(recipients), len(set(recipients)))
        self.assertEqual(Campaign.objects.get(pk=created.campaign.pk).status, 'completed')

    def test_a_recent_claim_is_left_alone(self) -> None:
        created = self.campaign_from(2)
        CampaignRecipient.objects.filter(address='p0@example.org').update(
            status='sending', claim_token='t', claimed_at=timezone.now()
        )
        campaign_runner.run()
        self.assertEqual(
            created.campaign.recipients.get(address='p0@example.org').status, 'sending'
        )


class EventsAndBouncesTests(MarketingBase):
    def line(self, queue_id: str, text: str) -> str:
        return f'Oct 15 09:00:00 mail postfix/{text}'.replace('QID', queue_id)

    def test_campaign_mail_is_remembered_with_its_campaign_and_the_log_is_followed(self) -> None:
        created = self.campaign_from(2)
        self.assertFalse(delivery_events._wanted())  # no event plugin, and nothing sent yet
        campaign_runner.run()
        self.assertTrue(delivery_events._wanted())  # marketing is active: its bounces matter
        message_id = created.campaign.recipients.get(address='p0@example.org').message_id
        remembered = delivery_events._sent(message_id)
        self.assertEqual(remembered.campaign, str(created.campaign.pk))
        self.assertEqual(remembered.sender, SENDER)
        self.assertEqual(remembered.key_prefix, 'abc123')

    def test_queued_events_go_to_webhooks_with_the_campaign_id(self) -> None:
        created = self.campaign_from(2)
        with patch.object(delivery_events.webhooks, 'emit_many') as emit:
            campaign_runner.run()
        events = emit.call_args.args[0]
        self.assertEqual(len(events), 2)
        self.assertEqual({e.type for e in events}, {'message.queued'})
        self.assertEqual({e.data['campaign'] for e in events}, {str(created.campaign.pk)})

    def test_a_hard_bounce_suppresses_the_address_even_without_sender_compliance(self) -> None:
        created = self.campaign_from(2)
        campaign_runner.run()
        row = created.campaign.recipients.get(address='p0@example.org')
        delivery_events.handle_line(
            self.line('Q1', f'cleanup[1]: Q1: message-id=<{row.message_id}>')
        )
        delivery_events.handle_line(
            self.line(
                'Q1',
                'smtp[2]: Q1: to=<p0@example.org>, relay=mx.example.org[1.2.3.4]:25, delay=1, '
                'dsn=5.1.1, status=bounced (550 5.1.1 User unknown)',
            )
        )
        gone = Suppression.objects.get(address='p0@example.org')
        self.assertEqual((gone.domain, gone.reason), ('ifinmail.test', 'bounced'))
        self.assertEqual(int(cache.get(f'marketing:bounced:{created.campaign.pk}')), 1)
        # ...and the next campaign to that list leaves them out
        again = self.campaign_from(2, name='again')
        self.assertEqual(again.skipped, {'suppressed': 1})

    def test_a_soft_bounce_is_counted_but_does_not_suppress(self) -> None:
        marketing.note_bounce('c1', SENDER, 'a@example.org', 'mailbox_full', '5.2.2', 'over quota')
        self.assertFalse(Suppression.objects.exists())
        self.assertEqual(int(cache.get('marketing:bounced:c1')), 1)

    def test_a_scan_batch_routes_campaign_bounces_too(self) -> None:
        created = self.campaign_from(2)
        campaign_runner.run()
        row = created.campaign.recipients.get(address='p1@example.org')
        batch = delivery_events._Batch(
            [
                self.line('Q9', f'cleanup[1]: Q9: message-id=<{row.message_id}>'),
                self.line(
                    'Q9',
                    'smtp[2]: Q9: to=<p1@example.org>, relay=mx.example.org[1.2.3.4]:25, delay=1, '
                    'dsn=5.1.1, status=bounced (550 5.1.1 User unknown)',
                ),
            ]
        )
        for line in batch._parsed:
            delivery_events.handle_line(line, batch)
        batch.flush()
        self.assertTrue(Suppression.objects.filter(address='p1@example.org').exists())
        self.assertEqual(int(cache.get(f'marketing:bounced:{created.campaign.pk}')), 1)


class UnsubscribeTests(MarketingBase):
    def link(self, address: str = 'ana@example.org') -> str:
        return reverse(
            'marketing_unsubscribe', args=[marketing.optout_token('ifinmail.test', address)]
        )

    def test_the_page_asks_and_a_scanner_opening_it_unsubscribes_no_one(self) -> None:
        response = self.client.get(self.link())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Stop marketing email')
        self.assertFalse(MarketingOptOut.objects.exists())

    def test_the_one_click_post_opts_out_of_marketing_only(self) -> None:
        response = self.client.post(self.link(), data={'List-Unsubscribe': 'One-Click'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'receipts')
        row = MarketingOptOut.objects.get()
        self.assertEqual(
            (row.domain, row.address, row.source), ('ifinmail.test', 'ana@example.org', 'one-click')
        )
        self.assertFalse(Suppression.objects.exists())  # not the all-mail suppression list
        self.assertContains(self.client.get(self.link()), 'will not get marketing email')

    def test_the_person_still_gets_receipts_after_unsubscribing_from_marketing(self) -> None:
        self.client.post(self.link(), data={'List-Unsubscribe': 'One-Click'})
        InstallationService.install('sender-compliance', {}, 'a')
        row, token = TokenService.create(
            self.owner, 'mailer', ['mail.send'], expires_in_days=30, allowed_senders=[SENDER]
        )
        response = self.call(
            'post',
            '/api/v1/messages',
            key=key_id(row.prefix),
            secret=token.split('.', 2)[2],
            body={
                'from': SENDER,
                'to': ['ana@example.org'],
                'subject': 'Your receipt',
                'text': 'Thanks',
            },
        )
        self.assertEqual(response.status_code, 202, response.content)
        self.assertEqual(mail.outbox[-1].to, ['ana@example.org'])

    def test_but_a_later_campaign_leaves_them_out(self) -> None:
        self.client.post(self.link('p0@example.org'), data={'List-Unsubscribe': 'One-Click'})
        created = self.campaign_from(3)
        self.assertEqual(created.skipped, {'opted_out': 1})

    def test_a_forged_or_altered_link_does_nothing(self) -> None:
        good = self.link()
        for path in (good[:-3] + 'xx/', reverse('marketing_unsubscribe', args=['garbage'])):
            with self.subTest(path=path):
                self.assertEqual(self.client.post(path, data={}).status_code, 404)
        self.assertFalse(MarketingOptOut.objects.exists())

    def test_a_link_for_the_other_kind_of_unsubscribe_does_not_work_here(self) -> None:
        from backend.apps.mail.services import compliance

        token = compliance.unsubscribe_token('news@ifinmail.test', 'ana@example.org')
        self.assertEqual(
            self.client.post(reverse('marketing_unsubscribe', args=[token])).status_code, 404
        )

    def test_an_opt_out_can_be_recorded_twice_without_harm(self) -> None:
        self.assertTrue(marketing.opt_out('ifinmail.test', 'a@example.org'))
        self.assertFalse(marketing.opt_out('IFINMAIL.test', 'A@example.org'))
        self.assertEqual(MarketingOptOut.objects.count(), 1)


class ServiceRulesTests(MarketingBase):
    def test_pause_resume_cancel_only_from_the_right_state(self) -> None:
        campaign = self.campaign_from(2).campaign
        self.assertFalse(marketing.resume(campaign))
        self.assertTrue(marketing.pause(campaign, 'because'))
        self.assertEqual(Campaign.objects.get(pk=campaign.pk).status_detail, 'because')
        self.assertTrue(marketing.resume(campaign))
        self.assertEqual(Campaign.objects.get(pk=campaign.pk).status_detail, '')
        self.assertTrue(marketing.cancel(campaign))
        self.assertFalse(marketing.cancel(campaign))
        self.assertFalse(marketing.pause(campaign))

    def test_internal_only_senders_cannot_run_campaigns(self) -> None:
        with (
            policy(**{'sending.internal_only': {'mailboxes': SENDER}}),
            self.assertRaises(SendRefused) as caught,
        ):
            self.campaign_from(2)
        self.assertEqual(caught.exception.status, 403)

    def test_the_footer_is_always_added(self) -> None:
        campaign = self.campaign_from(1, text='no unsubscribe link written here').campaign
        composed = marketing.compose(campaign, 'a@example.org', {}, ADDRESS)
        self.assertIn(ADDRESS, composed.text)
        self.assertIn('Unsubscribe: ', composed.text)
        self.assertEqual(composed.html, '')  # no html part was written, none is invented

    def test_a_subject_is_one_line_whatever_the_values_hold(self) -> None:
        campaign = self.campaign_from(
            1, subject='Hi {{first_name}}', text='x {{first_name}}'
        ).campaign
        hostile = {'first_name': 'Ana\r\nBcc: evil@example.org'}
        composed = marketing.compose(campaign, 'a@example.org', hostile, ADDRESS)
        self.assertNotIn('\n', composed.subject)
        self.assertNotIn('\r', composed.subject)

    def test_counts_for_many_campaigns_is_one_query_and_complete(self) -> None:
        a, b = self.campaign_from(2).campaign, self.campaign_from(3).campaign
        with self.assertNumQueries(1):
            found = marketing.counts_for([a, b])
        self.assertEqual((found[a.pk]['pending'], found[b.pk]['pending']), (2, 3))
        self.assertEqual(set(found[a.pk]), {'pending', 'sending', 'sent', 'failed', 'skipped'})
