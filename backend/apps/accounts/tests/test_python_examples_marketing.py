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
