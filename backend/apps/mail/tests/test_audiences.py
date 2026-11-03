"""Audiences: lists of people kept on the server, which a campaign can be sent to.

What these tests pin down: who may create and see an audience; that importing is idempotent and
reports exactly what happened; that "can this person be mailed" is looked up from the same
opt-out and suppression tables campaigns use, so it can never disagree with them; that a campaign
copies the list when it is created and only ever goes out from the audience's own domain; and that
the size limit refuses a batch whole rather than cutting a list in two.
"""

from __future__ import annotations

from django.test import override_settings

from backend.apps.accounts.tests import test_api_v1 as base
from backend.apps.core.plugins.services import InstallationService
from backend.apps.domains.models import Domain
from backend.apps.mail.models import (
    Audience,
    Campaign,
    CampaignRecipient,
    MarketingOptOut,
    Suppression,
)
from backend.apps.mail.services import audiences, marketing
from backend.apps.mail.tests.test_marketing import SENDER, MarketingBase

LISTS = '/api/v1/audiences'


class AudienceBase(MarketingBase):
    def setUp(self) -> None:
        super().setUp()
        self.auth, self.row = self.marketing_key()

    def api(self, method: str, path: str, body: dict | None = None, auth: dict | None = None):
        auth = auth or self.auth
        return self.call(method, path, key=auth['key'], secret=auth['secret'], body=body)

    def audience(self, name: str = 'Newsletter', domain: str = 'ifinmail.test') -> dict:
        response = self.api('post', LISTS, {'name': name, 'domain': domain})
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def add(self, audience_id: str, *contacts: dict, auth: dict | None = None):
        return self.api(
            'post', f'{LISTS}/{audience_id}/contacts', {'contacts': list(contacts)}, auth
        )

    def contacts(self, audience_id: str, query: str = '') -> list[dict]:
        response = self.api('get', f'{LISTS}/{audience_id}/contacts{query}')
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()['items']


class CreateAndSeeTests(AudienceBase):
    def test_an_audience_is_created_for_a_domain_the_key_sends_from(self) -> None:
        made = self.audience()
        self.assertEqual(made['domain'], 'ifinmail.test')
        self.assertEqual(
            made['contacts'], {'total': 0, 'reachable': 0, 'opted_out': 0, 'suppressed': 0}
        )

    def test_a_key_cannot_make_an_audience_for_a_domain_it_does_not_send_from(self) -> None:
        Domain.objects.create(name='other.test')
        response = self.api('post', LISTS, {'name': 'x', 'domain': 'other.test'})
        self.assertEqual(response.status_code, 403)
        response = self.api('post', LISTS, {'name': 'x', 'domain': 'nowhere.invalid'})
        self.assertEqual(response.status_code, 403)

    def test_the_name_is_required(self) -> None:
        for bad in ('', '   ', 'x' * 121):
            with self.subTest(name=bad):
                response = self.api('post', LISTS, {'name': bad, 'domain': 'ifinmail.test'})
                self.assertEqual(response.status_code, 422)

    def test_a_key_sees_only_its_own_audiences_and_a_manager_sees_all(self) -> None:
        mine = self.audience('mine')
        other_auth, _ = self.marketing_key()
        theirs = self.api('post', LISTS, {'name': 'theirs', 'domain': 'ifinmail.test'}, other_auth)
        self.assertEqual(theirs.status_code, 201)
        names = [a['name'] for a in self.api('get', LISTS).json()['items']]
        self.assertEqual(names, ['mine'])
        self.assertEqual(self.api('get', f'{LISTS}/{theirs.json()["id"]}').status_code, 404)
        self.assertEqual(self.api('get', f'{LISTS}/{mine["id"]}').status_code, 200)
        manager, _ = self.marketing_key(scopes=['marketing.send', 'mail.manage'])
        self.assertEqual(
            sorted(a['name'] for a in self.api('get', LISTS, auth=manager).json()['items']),
            ['mine', 'theirs'],
        )

    def test_another_keys_audience_cannot_be_changed_filled_or_deleted(self) -> None:
        mine = self.audience()
        other_auth, _ = self.marketing_key()
        path = f'{LISTS}/{mine["id"]}'
        self.assertEqual(self.api('patch', path, {'name': 'x'}, other_auth).status_code, 404)
        self.assertEqual(
            self.add(mine['id'], {'email': 'a@example.org'}, auth=other_auth).status_code, 404
        )
        self.assertEqual(self.api('delete', path, auth=other_auth).status_code, 404)
        self.assertTrue(Audience.objects.filter(pk=mine['id']).exists())

    def test_an_id_that_is_not_an_id_is_a_plain_404(self) -> None:
        self.assertEqual(self.api('get', f'{LISTS}/not-an-id').status_code, 404)

    def test_it_can_be_renamed_and_deleted(self) -> None:
        made = self.audience('Old')
        renamed = self.api('patch', f'{LISTS}/{made["id"]}', {'name': 'New', 'description': 'd'})
        self.assertEqual((renamed.json()['name'], renamed.json()['description']), ('New', 'd'))
        self.assertEqual(self.api('patch', f'{LISTS}/{made["id"]}', {'name': ' '}).status_code, 422)
        self.assertEqual(self.api('delete', f'{LISTS}/{made["id"]}').status_code, 204)
        self.assertEqual(self.api('get', f'{LISTS}/{made["id"]}').status_code, 404)

    def test_nothing_works_while_marketing_is_switched_off(self) -> None:
        made = self.audience()
        InstallationService.uninstall('marketing', 'a')
        self.assertEqual(
            self.api('post', LISTS, {'name': 'x', 'domain': 'ifinmail.test'}).status_code, 403
        )
        self.assertEqual(self.add(made['id'], {'email': 'a@example.org'}).status_code, 403)


class ImportTests(AudienceBase):
    def test_a_batch_says_what_happened_to_each_contact(self) -> None:
        made = self.audience()
        result = self.add(
            made['id'],
            {'email': 'Ana@Example.org', 'merge': {'first_name': 'Ana'}},
            {'email': 'ben@example.org'},
            {'email': 'ana@example.org'},  # the same person as the first, in other case
            {'email': 'not an address'},
            {'email': 'cy@example.org', 'merge': {'bad name': 'x'}},
        ).json()
        self.assertEqual(
            result, {'added': 2, 'updated': 0, 'unchanged': 0, 'invalid': 2, 'duplicate': 1}
        )
        self.assertEqual(
            {c['email']: c['merge'] for c in self.contacts(made['id'])},
            {'ana@example.org': {'first_name': 'Ana'}, 'ben@example.org': {}},
        )

    def test_sending_the_same_list_again_adds_nothing_and_changes_nothing(self) -> None:
        made = self.audience()
        batch = [{'email': f'p{i}@example.org', 'merge': {'first_name': f'P{i}'}} for i in range(5)]
        self.add(made['id'], *batch)
        again = self.add(made['id'], *batch).json()
        self.assertEqual((again['added'], again['updated'], again['unchanged']), (0, 0, 5))
        self.assertEqual(Audience.objects.get(pk=made['id']).contacts.count(), 5)

    def test_new_values_update_a_contact_and_leaving_them_out_keeps_the_old_ones(self) -> None:
        made = self.audience()
        self.add(made['id'], {'email': 'ana@example.org', 'merge': {'first_name': 'Ana'}})
        changed = self.add(
            made['id'], {'email': 'ana@example.org', 'merge': {'first_name': 'Anna'}}
        ).json()
        self.assertEqual((changed['updated'], changed['unchanged']), (1, 0))
        kept = self.add(made['id'], {'email': 'ana@example.org'}).json()
        self.assertEqual((kept['updated'], kept['unchanged']), (0, 1))
        self.assertEqual(self.contacts(made['id'])[0]['merge'], {'first_name': 'Anna'})

    def test_a_call_is_limited_to_a_thousand_contacts(self) -> None:
        made = self.audience()
        too_many = [{'email': f'p{i}@example.org'} for i in range(1001)]
        self.assertEqual(self.add(made['id'], *too_many).status_code, 422)
        self.assertEqual(self.add(made['id']).status_code, 422)  # and at least one

    def test_the_size_limit_refuses_a_batch_whole(self) -> None:
        self.configure(max_audience_size=5)
        made = self.audience()
        self.add(made['id'], *[{'email': f'p{i}@example.org'} for i in range(4)])
        refused = self.add(made['id'], *[{'email': f'q{i}@example.org'} for i in range(2)])
        self.assertEqual(refused.status_code, 422)
        self.assertIn('more than 5', refused.json()['detail'])
        self.assertEqual(
            Audience.objects.get(pk=made['id']).contacts.count(), 4
        )  # none of them went in
        # People already on the list can still be updated when it is full.
        self.add(made['id'], {'email': 'q0@example.org'})
        update = self.add(made['id'], {'email': 'p0@example.org', 'merge': {'a': 'b'}})
        self.assertEqual(update.status_code, 200)
        self.assertEqual(update.json()['updated'], 1)

    def test_a_contact_can_be_removed(self) -> None:
        made = self.audience()
        self.add(made['id'], {'email': 'ana@example.org'})
        path = f'{LISTS}/{made["id"]}/contacts/ANA@example.org'
        self.assertEqual(self.api('delete', path).status_code, 204)
        self.assertEqual(self.api('delete', path).status_code, 404)
        self.assertEqual(self.contacts(made['id']), [])

    def test_the_same_address_can_be_on_two_audiences(self) -> None:
        first, second = self.audience('a'), self.audience('b')
        for made in (first, second):
            self.assertEqual(self.add(made['id'], {'email': 'ana@example.org'}).json()['added'], 1)


class ReachabilityTests(AudienceBase):
    def fill(self) -> str:
        made = self.audience()
        self.add(
            made['id'], *[{'email': f'{n}@example.org'} for n in ('ok', 'out', 'gone', 'both')]
        )
        MarketingOptOut.objects.create(domain='ifinmail.test', address='out@example.org')
        MarketingOptOut.objects.create(domain='ifinmail.test', address='both@example.org')
        Suppression.objects.create(domain='ifinmail.test', address='gone@example.org')
        Suppression.objects.create(domain='ifinmail.test', address='both@example.org')
        return made['id']

    def test_each_contact_is_shown_as_reachable_opted_out_or_suppressed(self) -> None:
        audience_id = self.fill()
        shown = {c['email']: c['status'] for c in self.contacts(audience_id)}
        self.assertEqual(
            shown,
            {
                'ok@example.org': 'reachable',
                'out@example.org': 'opted_out',
                'gone@example.org': 'suppressed',
                'both@example.org': 'suppressed',  # the same precedence a campaign uses
            },
        )

    def test_the_counts_add_up(self) -> None:
        audience_id = self.fill()
        counted = self.api('get', f'{LISTS}/{audience_id}').json()['contacts']
        self.assertEqual(counted, {'total': 4, 'reachable': 1, 'opted_out': 1, 'suppressed': 2})

    def test_the_list_can_be_filtered(self) -> None:
        audience_id = self.fill()
        for status, expected in (
            ('reachable', {'ok@example.org'}),
            ('opted_out', {'out@example.org'}),
            ('suppressed', {'gone@example.org', 'both@example.org'}),
        ):
            with self.subTest(status=status):
                found = {c['email'] for c in self.contacts(audience_id, f'?status={status}')}
                self.assertEqual(found, expected)
        self.assertEqual(
            [c['email'] for c in self.contacts(audience_id, '?address=OK@example.org')],
            ['ok@example.org'],
        )
        self.assertEqual(
            self.api('get', f'{LISTS}/{audience_id}/contacts?status=nonsense').status_code, 422
        )

    def test_an_unsubscribe_from_any_campaign_shows_on_every_audience_of_the_domain(self) -> None:
        first, second = self.audience('a'), self.audience('b')
        for made in (first, second):
            self.add(made['id'], {'email': 'ana@example.org'})
        marketing.opt_out('ifinmail.test', 'ana@example.org', MarketingOptOut.ONE_CLICK)
        for made in (first, second):
            self.assertEqual(self.contacts(made['id'])[0]['status'], 'opted_out')

    def test_another_domains_opt_out_does_not_count(self) -> None:
        Domain.objects.create(name='other.test')
        self.fill()
        MarketingOptOut.objects.create(domain='other.test', address='ok@example.org')
        Suppression.objects.create(domain='other.test', address='ok@example.org')
        found = {c['email']: c['status'] for c in self.contacts(Audience.objects.get().pk.hex)}
        self.assertEqual(found['ok@example.org'], 'reachable')

    def test_counting_many_audiences_costs_one_query(self) -> None:
        for number in range(6):
            made = self.audience(f'list{number}')
            self.add(made['id'], *[{'email': f'p{i}@example.org'} for i in range(3)])
        rows = list(Audience.objects.all())
        with self.assertNumQueries(1):
            counted = audiences.counts_for(rows)
        self.assertEqual([c['total'] for c in counted.values()], [3] * 6)

    def test_listing_contacts_does_not_query_per_contact(self) -> None:
        made = self.audience()
        self.add(made['id'], *[{'email': f'p{i}@example.org'} for i in range(30)])
        # The key, the audience, one page of contacts with their status, and the count: 4,
        # whether the page holds 3 contacts or 30.
        with self.assertNumQueries(4):
            self.contacts(made['id'], '?limit=30')


class CampaignFromAudienceTests(AudienceBase):
    def send(self, audience_id: str, **body: object):
        payload = {
            'from': SENDER,
            'subject': 'Hello {{first_name|friend}}',
            'text': 'Hi {{first_name|friend}}',
            'audience': audience_id,
            **body,
        }
        return self.create(payload, auth=self.auth)

    def test_a_campaign_goes_to_everyone_who_can_be_mailed(self) -> None:
        made = self.audience()
        self.add(
            made['id'],
            *[{'email': f'p{i}@example.org', 'merge': {'first_name': f'P{i}'}} for i in range(5)],
        )
        MarketingOptOut.objects.create(domain='ifinmail.test', address='p0@example.org')
        Suppression.objects.create(domain='ifinmail.test', address='p1@example.org')
        response = self.send(made['id'])
        self.assertEqual(response.status_code, 202, response.content)
        body = response.json()
        self.assertEqual(body['queued'], 3)
        self.assertEqual(body['skipped'], {'opted_out': 1, 'suppressed': 1})
        campaign = Campaign.objects.get(pk=body['id'])
        self.assertEqual(str(campaign.audience_id), made['id'])
        shown = self.api('get', f'/api/v1/campaigns/{campaign.pk}').json()
        self.assertEqual(shown['audience'], made['id'])

    def test_the_contacts_values_fill_the_message_tags(self) -> None:
        made = self.audience()
        self.add(made['id'], {'email': 'ana@example.org', 'merge': {'first_name': 'Ana'}})
        body = {'subject': 'Hi {{first_name}}', 'text': 'Dear {{first_name}}'}
        campaign = Campaign.objects.get(pk=self.send(made['id'], **body).json()['id'])
        row = campaign.recipients.get()
        self.assertEqual(row.merge, {'first_name': 'Ana'})
        self.assertEqual(row.status, CampaignRecipient.PENDING)

    def test_a_tag_no_contact_has_a_value_for_is_still_a_typo(self) -> None:
        made = self.audience()
        self.add(made['id'], {'email': 'ana@example.org'})
        response = self.send(made['id'], text='Hi {{first_nmae}}')
        self.assertEqual(response.status_code, 422)
        self.assertIn('first_nmae', response.json()['detail'])
        self.assertFalse(Campaign.objects.exists())

    def test_the_audience_is_copied_when_the_campaign_is_created(self) -> None:
        made = self.audience()
        self.add(made['id'], *[{'email': f'p{i}@example.org'} for i in range(3)])
        campaign = Campaign.objects.get(pk=self.send(made['id']).json()['id'])
        self.add(made['id'], {'email': 'late@example.org'})
        self.api('delete', f'{LISTS}/{made["id"]}/contacts/p0@example.org')
        self.assertEqual(
            sorted(campaign.recipients.values_list('address', flat=True)),
            ['p0@example.org', 'p1@example.org', 'p2@example.org'],
        )

    def test_deleting_the_audience_leaves_the_campaign_alone(self) -> None:
        made = self.audience()
        self.add(made['id'], {'email': 'ana@example.org'})
        campaign = Campaign.objects.get(pk=self.send(made['id']).json()['id'])
        self.api('delete', f'{LISTS}/{made["id"]}')
        campaign.refresh_from_db()
        self.assertIsNone(campaign.audience_id)
        self.assertEqual(campaign.recipients.count(), 1)
        shown = self.api('get', f'/api/v1/campaigns/{campaign.pk}').json()
        self.assertIsNone(shown['audience'])

    def test_listing_recipients_and_an_audience_together_is_refused(self) -> None:
        made = self.audience()
        self.add(made['id'], {'email': 'ana@example.org'})
        response = self.send(made['id'], recipients=[{'email': 'b@example.org'}])
        self.assertEqual(response.status_code, 422)
        self.assertFalse(Campaign.objects.exists())

    def test_neither_recipients_nor_an_audience_is_refused(self) -> None:
        response = self.create({'from': SENDER, 'subject': 's', 'text': 't'}, auth=self.auth)
        self.assertEqual(response.status_code, 422)

    def test_an_empty_audience_is_refused(self) -> None:
        response = self.send(self.audience()['id'])
        self.assertEqual(response.status_code, 422)
        self.assertIn('no contacts', response.json()['detail'])

    def test_a_campaign_must_be_sent_from_the_audiences_own_domain(self) -> None:
        Domain.objects.create(name='other.test')
        auth, _ = self.marketing_key(senders=[SENDER, 'news@other.test'])
        made = self.api('post', LISTS, {'name': 'other', 'domain': 'other.test'}, auth).json()
        self.add(made['id'], {'email': 'ana@example.org'}, auth=auth)
        response = self.create(
            {'from': SENDER, 'subject': 's', 'text': 't', 'audience': made['id']}, auth=auth
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn('other.test', response.json()['detail'])
        ok = self.create(
            {'from': 'news@other.test', 'subject': 's', 'text': 't', 'audience': made['id']},
            auth=auth,
        )
        self.assertEqual(ok.status_code, 202, ok.content)

    def test_another_keys_audience_cannot_be_mailed(self) -> None:
        made = self.audience()
        self.add(made['id'], {'email': 'ana@example.org'})
        other_auth, _ = self.marketing_key()
        response = self.create(
            {'from': SENDER, 'subject': 's', 'text': 't', 'audience': made['id']}, auth=other_auth
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Campaign.objects.exists())

    def test_a_retry_with_the_same_idempotency_key_creates_one_campaign(self) -> None:
        made = self.audience()
        self.add(made['id'], {'email': 'ana@example.org'})
        body = {'from': SENDER, 'subject': 's', 'text': 't', 'audience': made['id']}
        first = self.create(body, headers={'HTTP_IDEMPOTENCY_KEY': 'abc'}, auth=self.auth)
        again = self.create(body, headers={'HTTP_IDEMPOTENCY_KEY': 'abc'}, auth=self.auth)
        self.assertEqual((first.status_code, again.status_code), (202, 202))
        self.assertEqual(first.json()['id'], again.json()['id'])
        self.assertEqual(Campaign.objects.count(), 1)

    def test_an_audience_campaign_is_held_to_the_audience_limit_not_the_request_limit(self) -> None:
        self.configure(max_recipients=2, max_audience_size=50)
        made = self.audience()
        self.add(made['id'], *[{'email': f'p{i}@example.org'} for i in range(10)])
        self.assertEqual(self.send(made['id']).status_code, 202)
        listed = self.create(
            {
                'from': SENDER,
                'subject': 's',
                'text': 't',
                'recipients': [{'email': f'q{i}@example.org'} for i in range(3)],
            },
            auth=self.auth,
        )
        self.assertEqual(listed.status_code, 422)


@override_settings(CACHES=base.LOCMEM)
class ServiceTests(AudienceBase):
    def test_a_key_without_a_sending_domain_cannot_create_one(self) -> None:
        key = audiences.AudienceKey(prefix='abc', domains=())
        with self.assertRaises(audiences.SendRefused):
            audiences.create('x', 'ifinmail.test', '', key)
        manager = audiences.AudienceKey(prefix='abc', domains=(), manager=True)
        self.assertEqual(
            audiences.create('x', 'ifinmail.test', '', manager).domain, 'ifinmail.test'
        )
