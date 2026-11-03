"""Templates: messages kept on the server, which a campaign can start from.

What these tests pin down: who may create and see a template; that a preview shows what a person
would get without sending anything and names the tags that would skip someone; that a campaign
copies the template when it is created (editing or deleting it later changes nothing that exists)
and that what the campaign gives wins over the template.
"""

from __future__ import annotations

from backend.apps.core.plugins.services import InstallationService
from backend.apps.mail.models import Campaign, Template
from backend.apps.mail.services import templates
from backend.apps.mail.tests.test_marketing import SENDER, MarketingBase, people

TEMPLATES = '/api/v1/templates'


class TemplateBase(MarketingBase):
    def setUp(self) -> None:
        super().setUp()
        self.auth, self.row = self.marketing_key()

    def api(self, method: str, path: str, body: dict | None = None, auth: dict | None = None):
        auth = auth or self.auth
        return self.call(method, path, key=auth['key'], secret=auth['secret'], body=body)

    def template(self, **fields: object) -> dict:
        body = {
            'name': 'Welcome',
            'subject': 'Hi {{first_name|friend}}',
            'text': 'Hello {{first_name|friend}}, see {{offer}}.',
            'html': '<p>Hello {{first_name|friend}}</p>',
            **fields,
        }
        response = self.api('post', TEMPLATES, body)
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def send(self, template_id: str | None, **body: object):
        payload = {'from': SENDER, 'recipients': people(2), **body}
        if template_id:
            payload['template'] = template_id
        return self.create(payload, auth=self.auth)


class CreateAndSeeTests(TemplateBase):
    def test_a_template_is_created_with_the_tags_it_uses(self) -> None:
        made = self.template()
        self.assertEqual(made['name'], 'Welcome')
        self.assertEqual(
            made['tags'],
            [{'name': 'first_name', 'required': False}, {'name': 'offer', 'required': True}],
        )

    def test_a_tag_needs_a_fallback_everywhere_to_not_be_required(self) -> None:
        made = self.template(subject='{{first_name|friend}}', text='{{first_name}}', html=None)
        self.assertEqual(made['tags'], [{'name': 'first_name', 'required': True}])

    def test_it_must_be_a_message_that_could_be_sent(self) -> None:
        for bad in (
            {'subject': 'two\nlines'},
            {'text': None, 'html': None},
            {'name': ' '},
            {'text': 'x' * 1_100_000, 'html': None},
        ):
            with self.subTest(bad=list(bad)):
                response = self.api(
                    'post',
                    TEMPLATES,
                    {'name': 'n', 'subject': 's', 'text': 't', 'html': None, **bad},
                )
                self.assertIn(response.status_code, (413, 422))
        self.assertFalse(Template.objects.exists())

    def test_a_key_sees_only_its_own_templates_and_a_manager_sees_all(self) -> None:
        mine = self.template(name='mine')
        other_auth, _ = self.marketing_key()
        theirs = self.api(
            'post', TEMPLATES, {'name': 'theirs', 'subject': 's', 'text': 't'}, other_auth
        )
        self.assertEqual(theirs.status_code, 201)
        self.assertEqual([t['name'] for t in self.api('get', TEMPLATES).json()['items']], ['mine'])
        self.assertEqual(self.api('get', f'{TEMPLATES}/{theirs.json()["id"]}').status_code, 404)
        manager, _ = self.marketing_key(scopes=['marketing.send', 'mail.manage'])
        listed = self.api('get', TEMPLATES, auth=manager).json()['items']
        self.assertEqual(sorted(t['name'] for t in listed), ['mine', 'theirs'])
        self.assertEqual(self.api('get', f'{TEMPLATES}/{mine["id"]}').status_code, 200)

    def test_another_keys_template_cannot_be_changed_deleted_or_used(self) -> None:
        mine = self.template()
        other_auth, _ = self.marketing_key()
        path = f'{TEMPLATES}/{mine["id"]}'
        self.assertEqual(self.api('patch', path, {'name': 'x'}, other_auth).status_code, 404)
        self.assertEqual(self.api('delete', path, auth=other_auth).status_code, 404)
        self.assertEqual(self.api('post', f'{path}/preview', {}, other_auth).status_code, 404)
        response = self.create(
            {'from': SENDER, 'template': mine['id'], 'recipients': people(1)}, auth=other_auth
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Campaign.objects.exists())

    def test_an_id_that_is_not_an_id_is_a_plain_404(self) -> None:
        self.assertEqual(self.api('get', f'{TEMPLATES}/nope').status_code, 404)

    def test_a_key_may_keep_only_so_many(self) -> None:
        for number in range(templates.MAX_PER_KEY):
            Template.objects.create(
                name=f't{number}', key_prefix=self.row.prefix, subject='s', text='t'
            )
        response = self.api('post', TEMPLATES, {'name': 'one more', 'subject': 's', 'text': 't'})
        self.assertEqual(response.status_code, 422)

    def test_nothing_works_while_marketing_is_switched_off(self) -> None:
        made = self.template()
        InstallationService.uninstall('marketing', 'a')
        response = self.api('post', TEMPLATES, {'name': 'n', 'subject': 's', 'text': 't'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            self.api('patch', f'{TEMPLATES}/{made["id"]}', {'name': 'x'}).status_code, 403
        )


class ChangeAndPreviewTests(TemplateBase):
    def test_only_what_is_sent_changes(self) -> None:
        made = self.template()
        path = f'{TEMPLATES}/{made["id"]}'
        changed = self.api('patch', path, {'subject': 'New {{first_name|friend}}'}).json()
        self.assertEqual(changed['subject'], 'New {{first_name|friend}}')
        self.assertEqual(changed['text'], made['text'])
        self.assertEqual(changed['name'], 'Welcome')

    def test_a_change_cannot_leave_it_unsendable(self) -> None:
        made = self.template(html=None)
        path = f'{TEMPLATES}/{made["id"]}'
        self.assertEqual(self.api('patch', path, {'text': ''}).status_code, 422)  # no body left
        self.assertEqual(Template.objects.get().text, made['text'])

    def test_a_template_can_be_deleted(self) -> None:
        made = self.template()
        self.assertEqual(self.api('delete', f'{TEMPLATES}/{made["id"]}').status_code, 204)
        self.assertEqual(self.api('get', f'{TEMPLATES}/{made["id"]}').status_code, 404)

    def test_a_preview_fills_the_tags_without_sending_anything(self) -> None:
        made = self.template()
        shown = self.api(
            'post',
            f'{TEMPLATES}/{made["id"]}/preview',
            {'merge': {'first_name': 'Ana', 'offer': '20% off'}, 'email': 'ana@example.org'},
        ).json()
        self.assertEqual(shown['subject'], 'Hi Ana')
        self.assertEqual(shown['text'], 'Hello Ana, see 20% off.')
        self.assertEqual(shown['missing'], [])
        self.assertEqual(len(self.outbox()), 0)

    def test_a_preview_names_the_tags_that_would_skip_someone(self) -> None:
        made = self.template()
        shown = self.api('post', f'{TEMPLATES}/{made["id"]}/preview', {}).json()
        self.assertEqual(shown['subject'], 'Hi friend')  # the fallback
        self.assertEqual(shown['missing'], ['offer'])
        self.assertIn('{{offer}}', shown['text'])  # left as written

    def test_a_preview_cannot_turn_a_value_into_markup(self) -> None:
        made = self.template(html='<p>{{first_name|x}}</p>', text=None)
        shown = self.api(
            'post',
            f'{TEMPLATES}/{made["id"]}/preview',
            {'merge': {'first_name': '<script>x</script>'}},
        ).json()
        self.assertEqual(shown['html'], '<p>&lt;script&gt;x&lt;/script&gt;</p>')

    def test_bad_merge_values_are_refused(self) -> None:
        made = self.template()
        response = self.api(
            'post', f'{TEMPLATES}/{made["id"]}/preview', {'merge': {'bad name': 'x'}}
        )
        self.assertEqual(response.status_code, 422)

    def outbox(self) -> list:
        from django.core import mail

        return mail.outbox


class CampaignFromTemplateTests(TemplateBase):
    def test_a_campaign_takes_its_message_from_the_template(self) -> None:
        made = self.template(text='Hello {{first_name|friend}}', subject='Hi {{first_name|friend}}')
        response = self.send(made['id'])
        self.assertEqual(response.status_code, 202, response.content)
        campaign = Campaign.objects.get(pk=response.json()['id'])
        self.assertEqual(str(campaign.template_id), made['id'])
        self.assertEqual(
            (campaign.subject, campaign.text, campaign.html),
            (
                'Hi {{first_name|friend}}',
                'Hello {{first_name|friend}}',
                '<p>Hello {{first_name|friend}}</p>',
            ),
        )
        shown = self.api('get', f'/api/v1/campaigns/{campaign.pk}').json()
        self.assertEqual(shown['template'], made['id'])

    def test_what_the_campaign_gives_wins_over_the_template(self) -> None:
        made = self.template(text='Hello {{first_name|friend}}')
        campaign = Campaign.objects.get(
            pk=self.send(made['id'], subject='A different subject', html='<b>mine</b>').json()['id']
        )
        self.assertEqual(campaign.subject, 'A different subject')
        self.assertEqual(campaign.html, '<b>mine</b>')
        self.assertEqual(campaign.text, 'Hello {{first_name|friend}}')  # not given: the template's

    def test_editing_or_deleting_the_template_does_not_change_the_campaign(self) -> None:
        made = self.template(text='Hello {{first_name|friend}}')
        campaign = Campaign.objects.get(pk=self.send(made['id']).json()['id'])
        self.api('patch', f'{TEMPLATES}/{made["id"]}', {'subject': 'Changed', 'text': 'Changed'})
        campaign.refresh_from_db()
        self.assertEqual(campaign.subject, 'Hi {{first_name|friend}}')
        self.assertEqual(campaign.text, 'Hello {{first_name|friend}}')
        self.api('delete', f'{TEMPLATES}/{made["id"]}')
        campaign.refresh_from_db()
        self.assertIsNone(campaign.template_id)
        self.assertEqual(campaign.subject, 'Hi {{first_name|friend}}')

    def test_the_templates_tags_are_checked_like_any_others(self) -> None:
        made = self.template(text='Hello {{offr}}')  # a typo no recipient has a value for
        response = self.send(made['id'])
        self.assertEqual(response.status_code, 422)
        self.assertIn('offr', response.json()['detail'])

    def test_without_a_template_the_subject_is_still_required(self) -> None:
        response = self.send(None, text='Hello')
        self.assertEqual(response.status_code, 422)
        self.assertIn('subject', response.json()['detail'])

    def test_a_template_with_no_body_of_its_own_can_be_given_one(self) -> None:
        made = self.template(text='Hello', html=None)
        self.assertEqual(self.send(made['id'], html='<p>Hello</p>').status_code, 202)

    def test_a_template_can_be_used_by_many_campaigns(self) -> None:
        made = self.template(text='Hello', subject='Hi')
        for _ in range(3):
            self.assertEqual(self.send(made['id']).status_code, 202)
        self.assertEqual(Campaign.objects.filter(template_id=made['id']).count(), 3)

    def test_a_template_sent_with_an_audience_works_too(self) -> None:
        from backend.apps.mail.tests.test_audiences import LISTS

        made = self.template(text='Hello {{first_name|friend}}', subject='Hi')
        audience = self.api('post', LISTS, {'name': 'a', 'domain': 'ifinmail.test'}).json()
        self.api(
            'post',
            f'{LISTS}/{audience["id"]}/contacts',
            {'contacts': [{'email': 'ana@example.org', 'merge': {'first_name': 'Ana'}}]},
        )
        response = self.create(
            {'from': SENDER, 'template': made['id'], 'audience': audience['id']}, auth=self.auth
        )
        self.assertEqual(response.status_code, 202, response.content)
