"""The marketing example (``examples/python/11_marketing_campaign.py``) and the client's campaign
methods run against the real API, like every other example (see ``test_python_examples``)."""

from __future__ import annotations

from pathlib import Path

from django.core import mail

from backend.apps.accounts.services.tokens import TokenService, key_id
from backend.apps.accounts.tests.test_python_examples import DjangoSession, ExampleBase


class MarketingExampleTests(ExampleBase):
    ADDRESS = 'Acme Ltd, 12 High Street, London N1 1AA, UK'

    def setUp(self) -> None:
        super().setUp()
        from backend.apps.core.plugins.services import InstallationService

        InstallationService.install(
            'marketing', {'postal_address': self.ADDRESS, 'warmup': False}, 'a'
        )
        row, token = TokenService.create(
            self.owner,
            'newsletter',
            ['marketing.send'],
            expires_in_days=30,
            allowed_senders=['news@ifinmail.test'],
        )
        self.marketer = self.module.Client(
            'http://testserver',
            key_id(row.prefix),
            token.split('.', 2)[2],
            session=DjangoSession(self.client),
            max_retries=0,
        )

    def files(self, people: str, text: str = 'Hello {{first_name|friend}}, spring is here.'):  # noqa: ANN201
        import tempfile

        folder = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: [p.unlink() for p in folder.iterdir()] and folder.rmdir())
        (folder / 'people.csv').write_text(people)
        (folder / 'body.txt').write_text(text)
        return str(folder / 'people.csv'), str(folder / 'body.txt')

    def test_the_client_creates_lists_and_controls_a_campaign(self) -> None:
        made = self.marketer.create_campaign(
            'news@ifinmail.test',
            'Hi {{first_name|friend}}',
            [
                {'email': 'ana@example.org', 'merge': {'first_name': 'Ana'}},
                {'email': 'bob@example.org'},
            ],
            text='Hello',
            name='spring',
        )
        self.assertEqual((made['status'], made['queued'], made['skipped']), ('sending', 2, {}))
        again = self.marketer.create_campaign(  # a retry of the same call must not create another
            'news@ifinmail.test',
            'Hi',
            [{'email': 'x@example.org'}],
            text='Hello',
            idempotency_key='k1',
        )
        self.assertEqual(
            again['id'],
            self.marketer.create_campaign(
                'news@ifinmail.test',
                'Hi',
                [{'email': 'x@example.org'}],
                text='Hello',
                idempotency_key='k1',
            )['id'],
        )
        state = self.marketer.campaign(made['id'])
        self.assertEqual(state['recipients']['pending'], 2)
        self.assertEqual({c['id'] for c in self.marketer.campaigns()}, {made['id'], again['id']})
        self.assertEqual([c['id'] for c in self.marketer.campaigns(status='paused')], [])
        self.assertEqual(self.marketer.pause_campaign(made['id'])['status'], 'paused')
        self.assertEqual(self.marketer.resume_campaign(made['id'])['status'], 'sending')
        self.assertEqual(
            sorted(r['email'] for r in self.marketer.campaign_recipients(made['id'])),
            ['ana@example.org', 'bob@example.org'],
        )
        self.assertEqual(self.marketer.cancel_campaign(made['id'])['status'], 'cancelled')
        self.assertEqual(
            self.marketer.wait_for_campaign(made['id'], timeout=0)['status'], 'cancelled'
        )

    def test_opt_outs_from_your_own_application(self) -> None:
        added = self.marketer.opt_out('Ana@Example.org', 'ifinmail.test')
        self.assertEqual(added['address'], 'ana@example.org')
        self.assertEqual([o['address'] for o in self.marketer.opt_outs()], ['ana@example.org'])
        with self.assertRaises(self.module.IfinmailError) as caught:
            self.marketer.opt_out('ana@example.org', 'ifinmail.test')
        self.assertEqual(caught.exception.status, 409)
        made = self.marketer.create_campaign(
            'news@ifinmail.test',
            'Hi',
            [{'email': 'ana@example.org'}, {'email': 'bob@example.org'}],
            text='x',
        )
        self.assertEqual((made['queued'], made['skipped']), (1, {'opted_out': 1}))

    def test_the_script_sends_a_campaign_from_a_csv_and_controls_it(self) -> None:
        from backend.apps.mail.services import campaign_runner

        people, body = self.files(
            'email,first_name\nana@example.org,Ana\nbob@example.org,\nana@example.org,Dup\n'
        )
        code, out, err = self.run_script(
            '11_marketing_campaign', 'send', 'news@ifinmail.test', 'Hi {{first_name|friend}}',
            body, people, '--name', 'spring', client=self.marketer,
        )  # fmt: skip
        self.assertEqual(code, 0, err)
        self.assertIn('created', out)
        self.assertIn('2 to be sent', out)
        self.assertIn('left out: 1 duplicate', out)
        campaign_id = out.split()[1].rstrip(':')
        code, out, _ = self.run_script(
            '11_marketing_campaign', 'status', campaign_id, client=self.marketer
        )
        self.assertIn('sending', out)
        self.assertIn('2 pending', out)
        code, out, _ = self.run_script(
            '11_marketing_campaign', 'pause', campaign_id, client=self.marketer
        )
        self.assertIn('paused', out)
        self.run_script('11_marketing_campaign', 'resume', campaign_id, client=self.marketer)
        campaign_runner.run()  # the server's pace allows the whole list at once
        code, out, _ = self.run_script(
            '11_marketing_campaign', 'status', campaign_id, '--watch', client=self.marketer
        )
        self.assertEqual(code, 0)
        self.assertIn('completed', out)
        self.assertIn('2 sent', out)
        by_person = {m.to[0]: m for m in mail.outbox}
        self.assertEqual(by_person['ana@example.org'].subject, 'Hi Ana')
        self.assertEqual(by_person['bob@example.org'].subject, 'Hi friend')  # the fallback

    def test_the_script_explains_what_went_wrong(self) -> None:
        people, body = self.files('email\nana@example.org\n')
        no_scope = self.sender(['news@ifinmail.test'])
        code, _, err = self.run_script(
            '11_marketing_campaign',
            'send',
            'news@ifinmail.test',
            'Hi',
            body,
            people,
            client=no_scope,
        )
        self.assertNotEqual(code, 0)
        self.assertIn('lacks marketing.send', err)
        code, _, err = self.run_script(
            '11_marketing_campaign',
            'send',
            'other@ifinmail.test',
            'Hi',
            body,
            people,
            client=self.marketer,
        )
        self.assertNotEqual(code, 0)
        bad, body2 = self.files('name\nana\n')
        code, _, err = self.run_script(
            '11_marketing_campaign',
            'send',
            'news@ifinmail.test',
            'Hi',
            body2,
            bad,
            client=self.marketer,
        )
        self.assertNotEqual(code, 0)
        self.assertIn('"email" column', err)

    def test_the_client_keeps_an_audience_and_sends_a_campaign_to_it(self) -> None:
        made = self.marketer.create_audience('Newsletter', 'ifinmail.test', 'everyone')
        done = self.marketer.add_contacts(
            made['id'],
            [{'email': f'p{i}@example.org', 'merge': {'first_name': f'P{i}'}} for i in range(7)],
            batch=3,  # three calls
        )
        self.assertEqual(
            done, {'added': 7, 'updated': 0, 'unchanged': 0, 'invalid': 0, 'duplicate': 0}
        )
        self.assertEqual(self.marketer.audience(made['id'])['contacts']['total'], 7)
        self.assertEqual([a['id'] for a in self.marketer.audiences()], [made['id']])
        self.marketer.opt_out('p0@example.org', 'ifinmail.test')
        self.assertEqual(
            [c['email'] for c in self.marketer.contacts(made['id'], status='opted_out')],
            ['p0@example.org'],
        )
        self.assertEqual(
            self.marketer.update_audience(made['id'], name='Renamed')['name'], 'Renamed'
        )
        sent = self.marketer.create_campaign(
            'news@ifinmail.test', 'Hi {{first_name}}', audience=made['id'], text='Hello'
        )
        self.assertEqual((sent['queued'], sent['skipped']), (6, {'opted_out': 1}))
        self.marketer.remove_contact(made['id'], 'p1@example.org')
        self.assertEqual(self.marketer.audience(made['id'])['contacts']['total'], 6)
        self.marketer.delete_audience(made['id'])
        self.assertEqual(list(self.marketer.audiences()), [])
        self.assertEqual(self.marketer.campaign(sent['id'])['recipients']['pending'], 6)

    def test_the_audience_script_loads_a_csv_and_the_campaign_script_sends_to_it(self) -> None:
        people, body = self.files(
            'email,first_name\nana@example.org,Ana\nbob@example.org,\nnope,x\n'
        )
        code, out, err = self.run_script(
            '12_audiences', 'new', 'Newsletter', 'ifinmail.test', client=self.marketer
        )
        self.assertEqual(code, 0, err)
        audience_id = out.split()[1]
        code, out, err = self.run_script(
            '12_audiences', 'import', audience_id, people, client=self.marketer
        )
        self.assertEqual((code, out.strip()), (0, '2 added, 1 invalid'), err)
        code, out, _ = self.run_script(
            '12_audiences', 'import', audience_id, people, client=self.marketer
        )
        self.assertEqual(out.strip(), '2 unchanged, 1 invalid')  # safe to run again
        code, out, _ = self.run_script('12_audiences', 'show', audience_id, client=self.marketer)
        self.assertIn('2 people: 2 reachable, 0 opted out, 0 suppressed', out)
        code, out, err = self.run_script(
            '11_marketing_campaign', 'send', 'news@ifinmail.test', 'Hi {{first_name|friend}}',
            body, '--audience', audience_id, client=self.marketer,
        )  # fmt: skip
        self.assertEqual(code, 0, err)
        self.assertIn('2 to be sent', out)
        code, out, _ = self.run_script(
            '12_audiences', 'contacts', audience_id, '--status', 'reachable', client=self.marketer
        )
        self.assertEqual(
            sorted(out.split('\n')[:2]),
            ['ana@example.org  reachable', 'bob@example.org  reachable'],
        )
        code, out, _ = self.run_script(
            '12_audiences', 'remove', audience_id, 'ana@example.org', client=self.marketer
        )
        self.assertIn('removed', out)
        code, out, _ = self.run_script('12_audiences', 'delete', audience_id, client=self.marketer)
        self.assertIn('deleted', out)

    def test_the_campaign_script_needs_exactly_one_of_a_csv_or_an_audience(self) -> None:
        people, body = self.files('email\nana@example.org\n')
        for extra in ((), (people, '--audience', 'x')):
            with self.subTest(extra=extra):
                code, _, err = self.run_script(
                    '11_marketing_campaign', 'send', 'news@ifinmail.test', 'Hi', body, *extra,
                    client=self.marketer,
                )  # fmt: skip
                self.assertNotEqual(code, 0)
                self.assertIn('not both', err)

    def test_the_client_keeps_templates_and_sends_from_one(self) -> None:
        made = self.marketer.create_template(
            'Welcome', 'Hi {{first_name|friend}}', text='Hello {{first_name|friend}} {{offer}}'
        )
        self.assertEqual(made['tags'][1], {'name': 'offer', 'required': True})
        self.assertEqual([t['id'] for t in self.marketer.templates()], [made['id']])
        shown = self.marketer.preview_template(made['id'], {'first_name': 'Ana'})
        self.assertEqual((shown['subject'], shown['missing']), ('Hi Ana', ['offer']))
        updated = self.marketer.update_template(made['id'], text='Hello {{first_name|friend}}')
        self.assertEqual(updated['text'], 'Hello {{first_name|friend}}')
        sent = self.marketer.create_campaign(
            'news@ifinmail.test', None, [{'email': 'ana@example.org'}], template=made['id']
        )
        self.assertEqual(sent['queued'], 1)
        self.assertEqual(self.marketer.campaign(sent['id'])['template'], made['id'])
        self.marketer.delete_template(made['id'])
        self.assertEqual(list(self.marketer.templates()), [])

    def test_the_client_schedules_moves_and_starts_a_campaign_and_reads_its_report(self) -> None:
        from datetime import timedelta

        from django.utils import timezone

        from backend.apps.mail.services import campaign_runner

        when = (timezone.now() + timedelta(days=2)).isoformat()
        made = self.marketer.create_campaign(
            'news@ifinmail.test',
            'Hi',
            [{'email': 'ana@example.org'}],
            html='<a href="https://shop.example.com/">shop</a>',
            send_at=when,
            track_opens=True,
        )
        self.assertEqual(made['status'], 'scheduled')
        later = (timezone.now() + timedelta(days=3)).isoformat()
        self.assertEqual(
            self.marketer.reschedule_campaign(made['id'], later)['status'], 'scheduled'
        )
        self.assertEqual(self.marketer.start_campaign(made['id'])['status'], 'sending')
        campaign_runner.run()
        report = self.marketer.campaign_report(made['id'])
        self.assertEqual((report['sent'], report['opens']['people']), (1, 0))
        self.assertEqual([link['clicks'] for link in report['links']], [0])
        self.assertEqual(
            [r['email'] for r in self.marketer.campaign_recipients(made['id'], opened=False)],
            ['ana@example.org'],
        )
        self.assertEqual(list(self.marketer.campaign_recipients(made['id'], clicked=True)), [])

    def test_the_template_script_and_the_campaign_script_work_together(self) -> None:
        from datetime import timedelta

        from django.utils import timezone

        people, body = self.files(
            'email,first_name\nana@example.org,Ana\n', text='Hi {{first_name|friend}}'
        )
        code, out, err = self.run_script(
            '13_templates',
            'new',
            'Welcome',
            'Hello {{first_name|friend}}',
            body,
            client=self.marketer,
        )
        self.assertEqual(code, 0, err)
        template_id = out.split()[1]
        code, out, _ = self.run_script('13_templates', 'list', client=self.marketer)
        self.assertIn('Welcome', out)
        code, out, _ = self.run_script(
            '13_templates', 'preview', template_id, 'first_name=Ana', client=self.marketer
        )
        self.assertIn('Subject: Hello Ana', out)
        code, out, _ = self.run_script(
            '13_templates', 'update', template_id, '--subject', 'Changed {{first_name|x}}',
            client=self.marketer,
        )  # fmt: skip
        self.assertIn('Changed', out)
        when = (timezone.now() + timedelta(days=1)).isoformat()
        code, out, err = self.run_script(
            '11_marketing_campaign', 'from-template', 'news@ifinmail.test', template_id, people,
            '--send-at', when, '--no-opens', client=self.marketer,
        )  # fmt: skip
        self.assertEqual(code, 0, err)
        self.assertIn('1 to be sent, starting', out)
        campaign_id = out.split()[1].rstrip(':')
        code, out, _ = self.run_script(
            '11_marketing_campaign', 'status', campaign_id, client=self.marketer
        )
        self.assertIn('scheduled', out)
        self.assertIn('starts', out)
        code, out, _ = self.run_script(
            '11_marketing_campaign', 'start', campaign_id, client=self.marketer
        )
        self.assertIn('sending', out)
        code, out, _ = self.run_script(
            '11_marketing_campaign', 'report', campaign_id, client=self.marketer
        )
        self.assertEqual(code, 0)
        self.assertIn('sent 0', out)
        code, out, _ = self.run_script('13_templates', 'delete', template_id, client=self.marketer)
        self.assertIn('deleted', out)
