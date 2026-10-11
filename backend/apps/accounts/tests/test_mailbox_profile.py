"""Profile page: identity, sessions, activity and advanced management for one mailbox."""

from __future__ import annotations

import uuid

from django.contrib.auth import authenticate
from django.contrib.sessions.models import Session
from django.test import Client
from django.urls import reverse

from backend.apps.accounts.models import MailUser
from backend.apps.core.tests.mail_base import MailTablesTestCase
from backend.apps.domains.models import Domain
from backend.apps.mail.models import Mailbox
from backend.apps.mail.services import MailboxService

GOOD = 'Correct-Horse-9'
MODEL_BACKEND = 'django.contrib.auth.backends.ModelBackend'


class MailboxProfileTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.make_domain()
        self.admin = MailUser.objects.create_user(
            'root@ifinmail.test', GOOD, is_staff=True, is_superuser=True
        )
        self.client.force_login(self.admin, backend=MODEL_BACKEND)
        from django.utils import timezone

        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()

    def profile_url(self, mailbox_id: object) -> str:
        return reverse('accounts:mailbox_profile', kwargs={'mailbox_id': mailbox_id})

    def sessions_url(self, mailbox_id: object) -> str:
        return reverse('accounts:mailbox_sessions_action', kwargs={'mailbox_id': mailbox_id})

    def test_profile_needs_an_administrator(self) -> None:
        mailbox, _ = MailboxService.create('ifinmail.test', 'alice', GOOD)
        url = self.profile_url(mailbox.id)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)
        plain = MailUser.objects.create_user('plain@ifinmail.test', GOOD)
        self.client.force_login(plain, backend=MODEL_BACKEND)
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_unknown_mailbox_is_a_404(self) -> None:
        response = self.client.get(self.profile_url(uuid.uuid4()))
        self.assertEqual(response.status_code, 404)

    def test_profile_shows_identity_security_activity_and_management(self) -> None:
        self.client.post(
            reverse('accounts:mailboxes_create'),
            {'local_part': 'alice', 'domain': 'ifinmail.test'},
        )
        mailbox = Mailbox.objects.get(local_part='alice')
        html = self.client.get(self.profile_url(mailbox.id)).content.decode()
        for section in (
            'alice@ifinmail.test',
            'Overview',
            'Security & sessions',
            'Activity',
            'Mail routing',
            'Manage',
            'Invite pending',
            'mailbox_created',
            'mailbox_invite_issued',
        ):
            self.assertIn(section, html)

    def test_login_without_mailbox_and_mailbox_without_login(self) -> None:
        Mailbox.objects.create(domain=Domain.objects.get(), local_part='orphan')
        orphan_id = Mailbox.objects.get(local_part='orphan').id
        html = self.client.get(self.profile_url(orphan_id)).content.decode()
        self.assertIn('mailbox without a login', html)
        self.assertIn('nothing to sign out', html)

    def test_revoke_one_session_and_revoke_all(self) -> None:
        mailbox, _ = MailboxService.create('ifinmail.test', 'alice', GOOD)
        address = 'alice@ifinmail.test'
        alice_client = Client()
        alice = MailUser.objects.get(email=address)
        alice_client.force_login(alice, backend=MODEL_BACKEND)
        alice_client.get(reverse('accounts:dashboard'))
        alice_key = alice_client.session.session_key
        self.assertTrue(
            Session.objects.filter(session_key=alice_key).exists()
        )
        # Revoking someone else's session works and is audited on the profile.
        response = self.client.post(
            self.sessions_url(mailbox.id),
            {'mailbox_id': str(mailbox.id), 'session_key': alice_key},
            follow=True,
        )
        self.assertContains(response, 'Ended one session')
        self.assertFalse(Session.objects.filter(session_key=alice_key).exists())
        # Revoke-all keeps the admin's own current session and reports the count.
        response = self.client.post(
            self.sessions_url(mailbox.id),
            {'mailbox_id': str(mailbox.id), 'revoke_all': 'on'},
            follow=True,
        )
        self.assertContains(response, 'no other live sessions')
        self.assertTrue(
            Session.objects.filter(session_key=self.client.session.session_key).exists()
        )

    def test_cannot_revoke_the_session_you_are_using(self) -> None:
        Mailbox.objects.create(domain=Domain.objects.get(), local_part='root')
        root_id = Mailbox.objects.get(local_part='root').id
        response = self.client.post(
            self.sessions_url(root_id),
            {
                'mailbox_id': str(root_id),
                'session_key': self.client.session.session_key,
            },
            follow=True,
        )
        self.assertContains(response, 'session you are using')
        self.assertEqual(self.client.get(reverse('accounts:mailboxes')).status_code, 200)

    def test_grant_and_revoke_admin_rights(self) -> None:
        mailbox, _ = MailboxService.create('ifinmail.test', 'alice', GOOD)
        act = reverse('accounts:mailboxes_action')
        self.client.post(
            act, {'action': 'grant_admin', 'address': 'alice@ifinmail.test'}
        )
        self.assertTrue(MailUser.objects.get(email='alice@ifinmail.test').is_staff)
        html = self.client.get(self.profile_url(mailbox.id)).content.decode()
        self.assertIn('Remove admin rights', html)
        self.client.post(
            act, {'action': 'revoke_admin', 'address': 'alice@ifinmail.test'}
        )
        self.assertFalse(MailUser.objects.get(email='alice@ifinmail.test').is_staff)

    def test_last_admin_cannot_be_demoted(self) -> None:
        from backend.apps.mail.types.provisioning import MailboxError

        # A lone staff login (no superuser cover) must keep its admin rights.
        self.admin.is_superuser = False
        self.admin.save(update_fields=['is_superuser'])
        Mailbox.objects.create(domain=Domain.objects.get(), local_part='root')
        with self.assertRaises(MailboxError):
            MailboxService.set_admin('root@ifinmail.test', False)
        self.assertTrue(MailUser.objects.get(email='root@ifinmail.test').is_staff)

    def test_profile_invite_shows_copyable_panel_once(self) -> None:
        mailbox, _ = MailboxService.create('ifinmail.test', 'alice', None)
        response = self.client.post(
            reverse('accounts:mailboxes_action'),
            {
                'action': 'invite',
                'address': 'alice@ifinmail.test',
                'return_to': 'profile',
            },
        )
        self.assertRedirects(
            response, self.profile_url(mailbox.id), fetch_redirect_response=False
        )
        html = self.client.get(self.profile_url(mailbox.id)).content.decode()
        self.assertIn('id="invite-link-value"', html)
        self.assertIn('data-action="copy-invite"', html)
        self.assertIn('/accounts/mailbox-setup/', html)
        # One-time: a refresh no longer shows the link.
        refreshed = self.client.get(self.profile_url(mailbox.id)).content.decode()
        self.assertNotIn('id="invite-link-value"', refreshed)

    def test_table_invite_still_uses_flash_message(self) -> None:
        MailboxService.create('ifinmail.test', 'alice', None)
        response = self.client.post(
            reverse('accounts:mailboxes_action'),
            {'action': 'invite', 'address': 'alice@ifinmail.test'},
            follow=True,
        )
        self.assertContains(response, 'Setup link for alice@ifinmail.test')
        self.assertContains(response, '/accounts/mailbox-setup/')

    def test_setting_password_via_invite_clears_pending_on_profile(self) -> None:
        from backend.apps.mail.services import MailboxInviteService

        mailbox, _ = MailboxService.create('ifinmail.test', 'alice', None)
        uid, token = MailboxInviteService.make_token('alice@ifinmail.test')
        self.client.post(
            reverse('accounts:mailbox_setup', kwargs={'uidb64': uid, 'token': token}),
            {'password': GOOD, 'password2': GOOD},
        )
        self.assertTrue(
            authenticate(username='alice@ifinmail.test', password=GOOD) is not None
        )
        html = self.client.get(self.profile_url(mailbox.id)).content.decode()
        self.assertNotIn('Invite pending', html)
