"""Open and click tracking, and the campaign report.

What these tests pin down: that only web links in the html are tracked and the unsubscribe link
never is; that a tracked address cannot be made to go anywhere but the link it was made for; that
opens and clicks are counted once per person and in total; that requests that are not a person are
sent on without being counted; that merge values in a link are filled in safely; and that the
report adds up.
"""

from __future__ import annotations

import re
from datetime import timedelta
from urllib.parse import urlsplit

from django.core import mail
from django.test import SimpleTestCase
from django.utils import timezone

from backend.apps.mail.models import Campaign, CampaignLink, CampaignRecipient
from backend.apps.mail.services import campaign_runner, marketing, tracking
from backend.apps.mail.tests.test_marketing import SENDER, MarketingBase, people

HTML = (
    '<html><body><p>Hi {{first_name|friend}}</p>'
    '<a href="https://shop.example.com/sale?utm=spring&amp;ref=a">Sale</a> '
    "<a class='b' href='https://shop.example.com/new'>New</a> "
    '<a href="https://shop.example.com/sale?utm=spring&amp;ref=a">Sale again</a> '
    '<a href="mailto:help@example.com">Mail us</a> <a href="#top">Top</a> '
    '<a href="{{unsubscribe_url}}">Unsubscribe here</a>'
    '</body></html>'
)


class LinkParsingTests(SimpleTestCase):
    def test_only_web_links_are_found_once_each_in_order(self) -> None:
        self.assertEqual(
            tracking.links_in(HTML),
            ['https://shop.example.com/sale?utm=spring&ref=a', 'https://shop.example.com/new'],
        )

    def test_nothing_that_is_not_a_web_address_is_tracked(self) -> None:
        for url in (
            'mailto:a@b.c',
            '#x',
            '{{unsubscribe_url}}',
            'javascript:alert(1)',
            '/relative',
        ):
            with self.subTest(url=url):
                self.assertFalse(tracking.trackable(url))
        self.assertFalse(tracking.trackable('https://x.example/' + 'a' * tracking.MAX_URL))

    def test_the_number_of_tracked_links_is_capped(self) -> None:
        html = ''.join(f'<a href="https://x.example/{i}">l</a>' for i in range(300))
        self.assertEqual(len(tracking.links_in(html)), tracking.MAX_LINKS)

    def test_only_tracked_links_are_rewritten(self) -> None:
        links = {'https://shop.example.com/new': 7}
        out = tracking.rewrite_links(HTML, 42, links)
        self.assertEqual(out.count('/t/c/42.7.'), 1)
        self.assertIn('href="https://shop.example.com/sale?utm=spring&amp;ref=a"', out)
        self.assertIn('mailto:help@example.com', out)
        self.assertIn('{{unsubscribe_url}}', out)


class TokenTests(SimpleTestCase):
    def test_tokens_round_trip(self) -> None:
        self.assertEqual(tracking.read_open_token(tracking.open_token(42)), 42)
        self.assertEqual(tracking.read_click_token(tracking.click_token(42, 7)), (42, 7))

    def test_a_token_cannot_be_changed(self) -> None:
        good = tracking.click_token(42, 7)
        for bad in (
            good.replace('42.', '43.', 1),
            good.replace('.7.', '.8.', 1),
            good[:-1] + '0',
            '',
            'x.y.z',
            '..',
        ):
            with self.subTest(bad=bad):
                self.assertIsNone(tracking.read_click_token(bad))
        self.assertIsNone(tracking.read_open_token(tracking.open_token(42).replace('42', '43', 1)))
        self.assertIsNone(tracking.read_open_token('nope'))

    def test_a_click_token_is_not_an_open_token_or_the_other_way(self) -> None:
        self.assertIsNone(tracking.read_open_token(tracking.click_token(42, 7)))
        self.assertIsNone(tracking.read_click_token(tracking.open_token(42)))

    def test_the_pixel_is_a_gif(self) -> None:
        self.assertTrue(tracking.PIXEL.startswith(b'GIF89a'))
        self.assertTrue(tracking.PIXEL.endswith(b';'))

    def test_machines_are_told_from_people(self) -> None:
        for agent in ('Googlebot/2.1', 'Mozilla/5.0 (compatible; Proofpoint)', 'curl/8.0', ''):
            if agent:
                self.assertTrue(tracking.is_machine(agent), agent)
        self.assertFalse(tracking.is_machine('Mozilla/5.0 (iPhone) AppleWebKit Safari'))
        self.assertFalse(tracking.is_machine('Mozilla/5.0 (via ggpht.com GoogleImageProxy)'))


class TrackBase(MarketingBase):
    def setUp(self) -> None:
        super().setUp()
        self.auth, self.row = self.marketing_key()

    def api(self, method: str, path: str, body: dict | None = None, auth: dict | None = None):
        auth = auth or self.auth
        return self.call(method, path, key=auth['key'], secret=auth['secret'], body=body)

    def run_campaign(self, n: int = 4, html: str = HTML, **fields: object) -> Campaign:
        body = {
            'from': SENDER,
            'subject': 'Hi',
            'text': 'Hello {{first_name|friend}}',
            'html': html,
            'recipients': people(n),
            **fields,
        }
        response = self.create(body, auth=self.auth)
        self.assertEqual(response.status_code, 202, response.content)
        campaign = Campaign.objects.get(pk=response.json()['id'])
        campaign_runner.run()
        return campaign

    def html_of(self, i: int = 0) -> str:
        return mail.outbox[i].alternatives[0].content

    def hrefs(self, i: int = 0) -> list[str]:
        return re.findall(r'href="([^"]*)"', self.html_of(i))

    def tracked(self, kind: str, i: int = 0) -> list[str]:
        return [urlsplit(u).path for u in self.hrefs(i) if f'/t/{kind}/' in u]

    def pixel(self, i: int = 0) -> str:
        found = re.search(r'src="([^"]*/t/o/[^"]*)"', self.html_of(i))
        assert found, self.html_of(i)
        return urlsplit(found.group(1).replace('&amp;', '&')).path

    def person(self, campaign: Campaign, address: str = 'p0@example.org'):  # noqa: ANN201
        return campaign.recipients.get(address=address)


class ComposeTests(TrackBase):
    def test_the_email_has_tracked_links_a_pixel_and_an_untouched_unsubscribe(self) -> None:
        self.run_campaign()
        html = self.html_of()
        self.assertEqual(len(self.tracked('c')), 3)  # all three web links
        self.assertEqual(len(set(self.tracked('c'))), 2)  # to two distinct ones, counted together
        self.assertIn('mailto:help@example.com', html)
        self.assertIn('href="#top"', html)
        self.assertEqual(html.count('/unsubscribe/m/'), 2)  # the one written, and the footer's
        self.assertNotIn('/t/c/', ''.join(u for u in self.hrefs() if '/unsubscribe/' in u))
        self.assertTrue(self.pixel().endswith('.gif'))
        self.assertLess(html.index('/t/o/'), html.index('</body>'))

    def test_every_person_has_their_own_addresses(self) -> None:
        self.run_campaign(3)
        self.assertEqual(len({self.pixel(i) for i in range(3)}), 3)
        self.assertEqual(len({tuple(self.tracked('c', i)) for i in range(3)}), 3)

    def test_the_plain_text_part_is_not_tracked(self) -> None:
        self.run_campaign(1, text='See https://shop.example.com/new')
        self.assertIn('https://shop.example.com/new', mail.outbox[0].body)
        self.assertNotIn('/t/c/', mail.outbox[0].body)

    def test_a_text_only_campaign_has_nothing_to_track(self) -> None:
        campaign = self.run_campaign(1, html=None)
        self.assertEqual((campaign.track_opens, campaign.track_clicks), (False, False))
        self.assertFalse(campaign.links.exists())

    def test_a_campaign_can_turn_either_off_for_itself(self) -> None:
        campaign = self.run_campaign(1, track_opens=False)
        self.assertEqual((campaign.track_opens, campaign.track_clicks), (False, True))
        self.assertNotIn('/t/o/', self.html_of())
        self.assertEqual(len(self.tracked('c')), 3)

    def test_the_plugin_default_applies_when_the_campaign_does_not_say(self) -> None:
        self.configure(track_opens=False, track_clicks=False)
        campaign = self.run_campaign(1)
        self.assertEqual((campaign.track_opens, campaign.track_clicks), (False, False))
        self.assertNotIn('/t/', self.html_of())
        again = self.run_campaign(1, track_clicks=True)
        self.assertEqual((again.track_opens, again.track_clicks), (False, True))

    def test_the_campaign_lists_its_links_and_says_what_it_tracks(self) -> None:
        campaign = self.run_campaign(1)
        self.assertEqual(
            list(campaign.links.values_list('url', flat=True)),
            ['https://shop.example.com/sale?utm=spring&ref=a', 'https://shop.example.com/new'],
        )
        shown = self.api('get', f'/api/v1/campaigns/{campaign.pk}').json()
        self.assertEqual((shown['track_opens'], shown['track_clicks']), (True, True))


class OpenTests(TrackBase):
    def test_an_open_is_counted_once_per_person_and_every_time_in_total(self) -> None:
        campaign = self.run_campaign()
        path = self.pixel()
        for _ in range(3):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Content-Type'], 'image/gif')
            self.assertEqual(response.content, tracking.PIXEL)
            self.assertIn('no-store', response['Cache-Control'])
        person = self.person(campaign)
        self.assertEqual(person.opens, 3)
        self.assertIsNotNone(person.first_opened_at)
        self.assertEqual(self.person(campaign, 'p1@example.org').opens, 0)

    def test_a_request_that_is_not_a_person_is_answered_and_not_counted(self) -> None:
        campaign = self.run_campaign()
        path = self.pixel()
        self.assertEqual(self.client.head(path).status_code, 200)
        self.assertEqual(
            self.client.get(
                path, HTTP_USER_AGENT='Mozilla/5.0 (compatible; Googlebot)'
            ).status_code,
            200,
        )
        self.assertEqual(self.person(campaign).opens, 0)

    def test_a_forged_or_unknown_address_is_a_404(self) -> None:
        self.run_campaign()
        self.assertEqual(self.client.get('/t/o/99999.deadbeefdeadbeefdead.gif').status_code, 404)
        self.assertEqual(self.client.get('/t/o/x.gif').status_code, 404)
        self.assertEqual(self.client.post(self.pixel()).status_code, 404)

    def test_opens_are_not_counted_for_a_campaign_that_does_not_track_them(self) -> None:
        campaign = self.run_campaign(2, track_opens=False)
        person = self.person(campaign)
        self.client.get(urlsplit(tracking.open_url(person.pk)).path)
        person.refresh_from_db()
        self.assertEqual(person.opens, 0)


class ClickTests(TrackBase):
    def click(self, campaign: Campaign, link: int = 0, i: int = 0, **extra: str):  # noqa: ANN201
        return self.client.get(self.tracked('c', i)[link], **extra)

    def test_a_click_is_counted_and_the_person_is_sent_on(self) -> None:
        campaign = self.run_campaign()
        response = self.click(campaign)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], 'https://shop.example.com/sale?utm=spring&ref=a')
        self.assertEqual(response['Referrer-Policy'], 'no-referrer')
        self.assertIn('no-store', response['Cache-Control'])
        person = self.person(campaign)
        self.assertEqual(person.clicks, 1)
        self.assertIsNotNone(person.first_clicked_at)
        link = campaign.links.get(position=0)
        self.assertEqual((link.clicks, link.unique_clicks), (1, 1))

    def test_clicking_again_counts_the_total_but_not_the_person_twice(self) -> None:
        campaign = self.run_campaign()
        for _ in range(3):
            self.click(campaign)
        self.click(campaign, link=1)
        link0, link1 = campaign.links.all()
        self.assertEqual((link0.clicks, link0.unique_clicks), (3, 1))
        self.assertEqual((link1.clicks, link1.unique_clicks), (1, 1))
        self.assertEqual(self.person(campaign).clicks, 4)
        self.click(campaign, i=1)  # another person
        link0.refresh_from_db()
        self.assertEqual((link0.clicks, link0.unique_clicks), (4, 2))

    def test_a_scanner_is_sent_on_without_being_counted(self) -> None:
        campaign = self.run_campaign()
        response = self.click(campaign, HTTP_USER_AGENT='Barracuda Link Scanner')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.head(self.tracked('c')[0]).status_code, 302)
        self.assertEqual(self.person(campaign).clicks, 0)
        self.assertEqual(campaign.links.get(position=0).clicks, 0)

    def test_merge_values_in_a_link_are_filled_in_and_cannot_change_the_address(self) -> None:
        html = (
            '<a href="https://shop.example.com/u/{{id}}?e={{email}}&amp;n={{first_name|x}}">go</a>'
        )
        body = {
            'from': SENDER,
            'subject': 'Hi',
            'html': html,
            'recipients': [
                {'email': 'a@example.org', 'merge': {'id': '7', 'first_name': 'Ana & Bob/../x?y#z'}}
            ],
        }
        self.assertEqual(self.create(body, auth=self.auth).status_code, 202)
        campaign_runner.run()
        location = self.client.get(self.tracked('c')[0])['Location']
        self.assertEqual(
            location,
            'https://shop.example.com/u/7?e=a%40example.org&n=Ana%20%26%20Bob%2F..%2Fx%3Fy%23z',
        )

    def test_a_forged_address_is_a_404_and_counts_nothing(self) -> None:
        campaign = self.run_campaign()
        good = self.tracked('c')[0]
        for bad in (good[:-2] + 'x/', '/t/c/1.1.deadbeefdeadbeefdead/', '/t/c/garbage/'):
            with self.subTest(bad=bad):
                self.assertEqual(self.client.get(bad).status_code, 404)
        self.assertEqual(self.person(campaign).clicks, 0)

    def test_a_link_of_another_campaign_cannot_be_reached_with_someone_elses_token(self) -> None:
        first = self.run_campaign(1)
        second = self.run_campaign(1)
        person = first.recipients.get()
        foreign = second.links.get(position=0)
        self.assertIsNone(tracking.record_click(person.pk, foreign.pk))
        self.assertEqual(
            self.client.get(f'/t/c/{tracking.click_token(person.pk, foreign.pk)}/').status_code, 404
        )

    def test_the_redirect_only_ever_goes_to_a_web_address(self) -> None:
        campaign = self.run_campaign(1)
        CampaignLink.objects.filter(campaign=campaign, position=0).update(url='javascript:alert(1)')
        self.assertEqual(self.click(campaign).status_code, 404)
        CampaignLink.objects.filter(campaign=campaign, position=0).update(url='https://{{id}}.x/')
        self.assertEqual(self.click(campaign).status_code, 404)  # a tag with no value is no address

    def test_clicks_are_not_counted_for_a_campaign_that_does_not_track_them(self) -> None:
        campaign = self.run_campaign(1, track_clicks=False)
        self.assertEqual(self.tracked('c'), [])
        person = self.person(campaign)
        self.assertEqual(person.clicks, 0)

    def test_a_cancelled_campaigns_links_still_work(self) -> None:
        campaign = self.run_campaign()
        marketing.cancel(campaign)
        self.assertEqual(self.click(campaign).status_code, 302)


class ReportTests(TrackBase):
    def test_the_report_adds_up(self) -> None:
        campaign = self.run_campaign(4)
        for _ in range(2):
            self.client.get(self.pixel(0))
        self.client.get(self.pixel(1))
        self.client.get(self.tracked('c', 0)[0])
        self.client.get(self.tracked('c', 0)[0])
        self.client.get(self.tracked('c', 2)[1])
        report = self.api('get', f'/api/v1/campaigns/{campaign.pk}/report').json()
        self.assertEqual(report['sent'], 4)
        self.assertEqual((report['failed'], report['skipped']), (0, 0))
        self.assertEqual(report['tracking'], {'opens': True, 'clicks': True})
        self.assertEqual(report['opens'], {'people': 2, 'total': 3, 'rate': 50.0})
        self.assertEqual(
            report['clicks'], {'people': 2, 'total': 3, 'rate': 50.0, 'of_openers': 50.0}
        )
        self.assertEqual(
            report['links'],
            [
                {'url': 'https://shop.example.com/sale?utm=spring&ref=a', 'clicks': 2, 'people': 1},
                {'url': 'https://shop.example.com/new', 'clicks': 1, 'people': 1},
            ],
        )
        self.assertEqual(sum(p['opens'] for p in report['timeline']), 2)  # people, not opens
        self.assertEqual(sum(p['clicks'] for p in report['timeline']), 2)

    def test_a_campaign_nobody_opened_has_zero_not_nothing(self) -> None:
        campaign = self.run_campaign(2)
        report = self.api('get', f'/api/v1/campaigns/{campaign.pk}/report').json()
        self.assertEqual(report['opens'], {'people': 0, 'total': 0, 'rate': 0.0})
        self.assertEqual(report['timeline'], [])

    def test_a_campaign_that_has_sent_nothing_has_no_rates(self) -> None:
        response = self.create(
            {'from': SENDER, 'subject': 's', 'html': '<p>x</p>', 'recipients': people(1)},
            auth=self.auth,
        )
        report = self.api('get', f'/api/v1/campaigns/{response.json()["id"]}/report').json()
        self.assertEqual((report['sent'], report['opens']['rate']), (0, None))

    def test_the_timeline_can_be_by_the_day(self) -> None:
        campaign = self.run_campaign(2)
        self.client.get(self.pixel(0))
        CampaignRecipient.objects.filter(pk=self.person(campaign).pk).update(
            first_opened_at=timezone.now() - timedelta(days=2)
        )
        self.client.get(self.pixel(1))
        by_day = self.api('get', f'/api/v1/campaigns/{campaign.pk}/report?by=day').json()
        self.assertEqual(len(by_day['timeline']), 2)
        self.assertTrue(all(p['at'].endswith('T00:00:00+00:00') for p in by_day['timeline']))
        self.assertEqual(
            self.api('get', f'/api/v1/campaigns/{campaign.pk}/report?by=week').status_code, 422
        )

    def test_another_keys_report_is_a_404(self) -> None:
        campaign = self.run_campaign(1)
        other, _ = self.marketing_key()
        self.assertEqual(
            self.api('get', f'/api/v1/campaigns/{campaign.pk}/report', auth=other).status_code, 404
        )

    def test_recipients_show_and_filter_by_engagement(self) -> None:
        campaign = self.run_campaign(4)
        self.client.get(self.pixel(0))
        self.client.get(self.tracked('c', 1)[0])
        path = f'/api/v1/campaigns/{campaign.pk}/recipients'
        opened = self.api('get', f'{path}?opened=true').json()['items']
        self.assertEqual([r['email'] for r in opened], ['p0@example.org'])
        self.assertEqual(opened[0]['opens'], 1)
        clicked = self.api('get', f'{path}?clicked=true').json()['items']
        self.assertEqual([r['email'] for r in clicked], ['p1@example.org'])
        self.assertEqual(clicked[0]['clicks'], 1)
        silent = self.api('get', f'{path}?opened=false&clicked=false').json()['items']
        self.assertEqual(sorted(r['email'] for r in silent), ['p2@example.org', 'p3@example.org'])

    def test_the_report_costs_a_fixed_number_of_queries(self) -> None:
        campaign = self.run_campaign(6)
        for i in range(6):
            self.client.get(self.pixel(i))
        path = f'/api/v1/campaigns/{campaign.pk}/report'
        with self.assertNumQueries(10):
            self.api('get', path)
