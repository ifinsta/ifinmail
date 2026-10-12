"""End-to-end flows through the real views: setup wizard, mailboxes, registration."""

from __future__ import annotations

import json
from unittest.mock import patch

from django.contrib.auth import authenticate
from django.test import override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from backend.apps.accounts.models import MailUser
from backend.apps.accounts.services.registration_policy import (
    registration_open,
    set_registration_open,
)
from backend.apps.accounts.services.setup_state import SetupState
from backend.apps.accounts.views.registration import token_generator
from backend.apps.core.tests.mail_base import MailTablesTestCase
from backend.apps.domains.models import DKIMKey, Domain
from backend.apps.mail.models import Alias, Mailbox
from backend.apps.mail.services import MailboxService

GOOD = 'Correct-Horse-9'
MODEL_BACKEND = 'django.contrib.auth.backends.ModelBackend'
_LOOKUP = 'backend.apps.domains.services.verification._lookup'


class _Base(MailTablesTestCase):
    def login_admin(self, email: str = 'root@ifinmail.test') -> MailUser:
        admin = MailUser.objects.create_user(email, GOOD, is_staff=True, is_superuser=True)
        self.client.force_login(admin, backend=MODEL_BACKEND)
        from django.utils import timezone

        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()
        return admin


class SetupWizardFlowTests(_Base):
    """The wizard used to redirect to the dashboard the moment any admin existed."""

    def test_a_fresh_install_with_only_the_bootstrap_admin_opens_the_wizard(self) -> None:
        self.login_admin()
        self.assertFalse(SetupState.is_complete())
        response = self.client.get(reverse('accounts:setup_wizard'))
        self.assertRedirects(
            response,
            reverse('accounts:setup_step', kwargs={'step': 'welcome'}),
            fetch_redirect_response=False,
        )
        self.assertEqual(
            self.client.get(reverse('accounts:setup_step', kwargs={'step': 'welcome'})).status_code,
            200,
        )

    def test_walking_the_whole_wizard_provisions_the_server_and_finishes_setup(self) -> None:
        self.login_admin('admin@ifinmail.test')
        advance = reverse('accounts:setup_advance')
        with (
            patch(_LOOKUP, return_value=[]),
            patch('backend.apps.dns.services.DNSService.get_server_ip', return_value='203.0.113.5'),
        ):
            self.client.post(advance, {'current_step': 'welcome', 'domain': 'ifinmail.test'})
            self.assertTrue(Domain.objects.filter(name='ifinmail.test').exists())
            self.assertEqual(DKIMKey.objects.count(), 1)  # key exists before any DNS is shown
            self.client.post(advance, {'current_step': 'dns', 'skip': '1'})
            page = self.client.get(reverse('accounts:setup_step', kwargs={'step': 'dns-manual'}))
            self.client.get(reverse('accounts:setup_step', kwargs={'step': 'dns-manual'}))
            self.assertIn(page.status_code, (200, 302))
            self.client.post(
                advance,
                {'current_step': 'account', 'email': 'admin@ifinmail.test', 'password': GOOD},
            )
        self.assertTrue(Mailbox.objects.filter(local_part='admin').exists())
        self.assertEqual(MailUser.objects.filter(email='admin@ifinmail.test').count(), 1)
        self.assertTrue(authenticate(username='admin@ifinmail.test', password=GOOD))
        self.assertTrue(SetupState.is_complete())  # a mailbox now exists
        self.client.post(advance, {'current_step': 'done'})
        response = self.client.get(reverse('accounts:setup_wizard'))
        self.assertRedirects(response, reverse('accounts:dashboard'), fetch_redirect_response=False)

    def test_a_bad_account_shows_the_reason_and_stays_on_the_step(self) -> None:
        self.login_admin()
        advance = reverse('accounts:setup_advance')
        self.client.post(advance, {'current_step': 'welcome', 'domain': 'ifinmail.test'})
        response = self.client.post(
            advance,
            {'current_step': 'account', 'email': 'someone@ifinmail.test', 'password': 'short'},
            follow=True,
        )
        self.assertContains(response, 'at least 8 characters')
        self.assertFalse(Mailbox.objects.exists())

    def test_finishing_or_skipping_marks_setup_complete_even_without_a_mailbox(self) -> None:
        self.login_admin()
        self.client.post(reverse('accounts:setup_advance'), {'current_step': 'done'})
        self.assertTrue(SetupState.is_complete())


class MailboxLoginTests(_Base):
    def test_a_plain_mailbox_login_gets_mail_settings_instead_of_a_silent_bounce(self) -> None:
        self.make_domain()
        MailboxService.create('ifinmail.test', 'alice', GOOD)
        response = self.client.post(
            reverse('accounts:login'), {'email': 'alice@ifinmail.test', 'password': GOOD}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'alice@ifinmail.test is a mailbox')
        self.assertContains(response, 'mail.ifinmail.test')
        self.assertNotIn('_auth_user_id', self.client.session)  # no console session was created
        self.assertEqual(self.client.get(reverse('accounts:mailboxes')).status_code, 302)


class MailboxPagesTests(_Base):
    def setUp(self) -> None:
        super().setUp()
        self.make_domain()
        self.admin = self.login_admin()

    def test_pages_require_an_administrator(self) -> None:
        self.client.logout()
        for name in ('accounts:mailboxes', 'accounts:aliases'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 302)
        plain = MailUser.objects.create_user('plain@ifinmail.test', GOOD)
        self.client.force_login(plain, backend=MODEL_BACKEND)
        self.assertEqual(self.client.get(reverse('accounts:mailboxes')).status_code, 302)
        self.assertEqual(
            self.client.post(
                reverse('accounts:mailboxes_create'),
                {'local_part': 'x', 'domain': 'ifinmail.test', 'password': GOOD},
            ).status_code,
            302,
        )
        self.assertFalse(Mailbox.objects.exists())

    def test_get_only_pages_reject_posting_and_actions_reject_get(self) -> None:
        self.assertEqual(self.client.get(reverse('accounts:mailboxes_create')).status_code, 405)
        self.assertEqual(self.client.post(reverse('accounts:mailboxes')).status_code, 405)

    def test_create_change_and_remove_a_mailbox_from_the_console(self) -> None:
        response = self.client.post(
            reverse('accounts:mailboxes_create'),
            {'local_part': 'Alice', 'domain': 'ifinmail.test', 'quota_mb': '50'},
            follow=True,
        )
        self.assertContains(response, 'Created alice@ifinmail.test')
        self.assertContains(response, 'setup link')
        self.assertEqual(Mailbox.objects.get().quota_bytes, 50 * 1024 * 1024)
        self.assertContains(response, '50 MB')
        address = 'alice@ifinmail.test'
        # Invite-pending: no usable password until the owner accepts the link.
        pending = MailboxService.list_rows()[0]
        self.assertTrue(pending.invite_pending)
        self.assertIsNone(authenticate(username=address, password='New-Pass-1234'))
        act = reverse('accounts:mailboxes_action')
        response = self.client.post(act, {'action': 'invite', 'address': address}, follow=True)
        self.assertContains(response, 'Setup link for alice@ifinmail.test')
        # Owner accepts the setup link (single-use).
        from backend.apps.mail.services import MailboxInviteService

        uid, token = MailboxInviteService.make_token(address)
        setup = reverse('accounts:mailbox_setup', kwargs={'uidb64': uid, 'token': token})
        self.assertEqual(self.client.get(setup).status_code, 200)
        response = self.client.post(
            setup,
            {'password': 'New-Pass-1234', 'password2': 'New-Pass-1234'},
            follow=True,
        )
        self.assertTrue(authenticate(username=address, password='New-Pass-1234'))
        self.assertIsNone(MailboxInviteService.check_token(uid, token))  # single-use: consumed
        self.assertFalse(MailboxService.list_rows()[0].invite_pending)
        self.client.post(act, {'action': 'quota', 'address': address, 'quota_mb': '0'})
        self.assertEqual(Mailbox.objects.get().quota_bytes, 0)
        self.client.post(act, {'action': 'disable', 'address': address})
        self.assertFalse(MailUser.objects.get(email=address).is_active)
        self.client.post(act, {'action': 'enable', 'address': address})
        self.assertTrue(MailUser.objects.get(email=address).is_active)
        response = self.client.post(act, {'action': 'delete', 'address': address}, follow=True)
        self.assertContains(response, 'Removed alice@ifinmail.test')
        self.assertFalse(Mailbox.objects.exists())

    @patch.dict('os.environ', {'MAIL_HOSTNAME': 'mail.ifinmail.test'})
    def test_the_setup_link_is_emailed_to_the_given_address(self) -> None:
        from django.core import mail

        response = self.client.post(
            reverse('accounts:mailboxes_create'),
            {'local_part': 'dana', 'domain': 'ifinmail.test', 'send_to': 'Dana@Example.com'},
            follow=True,
        )
        self.assertContains(response, 'were sent to dana@example.com')
        self.assertNotContains(response, '/accounts/mailbox-setup/')
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.to, ['dana@example.com'])
        self.assertEqual(sent.subject, 'Set up your mailbox dana@ifinmail.test')
        html = sent.alternatives[0][0]
        for body in (sent.body, html):
            self.assertIn('/accounts/mailbox-setup/', body)
            self.assertIn('mail.ifinmail.test, port 993', body)
            self.assertIn('expires in 3 days', body)
        # The emailed link works.
        link = sent.body.split('http://testserver', 1)[1].split()[0]
        self.assertContains(
            self.client.get(link), 'Choose a password for <strong>dana@ifinmail.test'
        )

    def test_the_setup_link_cannot_be_sent_to_the_new_mailbox_itself(self) -> None:
        from django.core import mail

        response = self.client.post(
            reverse('accounts:mailboxes_create'),
            {'local_part': 'dana', 'domain': 'ifinmail.test', 'send_to': 'dana@ifinmail.test'},
            follow=True,
        )
        self.assertContains(response, 'already read')
        self.assertFalse(Mailbox.objects.exists())
        self.assertEqual(mail.outbox, [])

    def test_a_failed_email_still_shows_the_link(self) -> None:
        with patch(
            'backend.apps.accounts.views.mailboxes.send_mail', side_effect=ConnectionError('down')
        ):
            response = self.client.post(
                reverse('accounts:mailboxes_create'),
                {'local_part': 'dana', 'domain': 'ifinmail.test', 'send_to': 'dana@example.com'},
                follow=True,
            )
        self.assertContains(response, 'could not be sent')
        self.assertContains(response, '/accounts/mailbox-setup/')
        self.assertTrue(Mailbox.objects.exists())

    def test_a_new_setup_link_can_be_emailed_to_another_address(self) -> None:
        from django.core import mail

        self.client.post(
            reverse('accounts:mailboxes_create'),
            {'local_part': 'dana', 'domain': 'ifinmail.test'},
            follow=True,  # consume the create message, which shows a link
        )
        act = reverse('accounts:mailboxes_action')
        payload = {'action': 'invite', 'address': 'dana@ifinmail.test'}
        response = self.client.post(act, {**payload, 'send_to': 'dana@example.com'}, follow=True)
        self.assertContains(response, 'were sent to dana@example.com')
        self.assertNotContains(response, '/accounts/mailbox-setup/')
        self.assertEqual(mail.outbox[-1].to, ['dana@example.com'])
        self.assertIn('/accounts/mailbox-setup/', mail.outbox[-1].body)

        # From the profile page: back to the profile, no copy panel.
        mailbox_id = MailboxService.mailbox_id_for('dana@ifinmail.test')
        response = self.client.post(
            act, {**payload, 'send_to': 'other@example.com', 'return_to': 'profile'}
        )
        self.assertRedirects(
            response, reverse('accounts:mailbox_profile', kwargs={'mailbox_id': mailbox_id})
        )
        self.assertNotIn('invite_link', self.client.session)
        self.assertEqual(mail.outbox[-1].to, ['other@example.com'])

        # Not to the mailbox itself.
        sent = len(mail.outbox)
        response = self.client.post(act, {**payload, 'send_to': 'dana@ifinmail.test'}, follow=True)
        self.assertContains(response, 'already read')
        self.assertEqual(len(mail.outbox), sent)

    def test_errors_are_shown_and_nothing_is_created(self) -> None:
        response = self.client.post(
            reverse('accounts:mailboxes_create'),
            {'local_part': 'bad..name', 'domain': 'ifinmail.test'},
            follow=True,
        )
        self.assertContains(response, 'two dots')
        self.assertFalse(Mailbox.objects.exists())

    def test_console_created_mailboxes_default_to_1024_mb(self) -> None:
        from backend.apps.mail.types.quota import DEFAULT_QUOTA_BYTES

        # No quota_mb field at all (older form posts) and a blank field both
        # mean "default", not "unlimited".
        for payload in (
            {'local_part': 'bob', 'domain': 'ifinmail.test'},
            {'local_part': 'carol', 'domain': 'ifinmail.test', 'quota_mb': ''},
        ):
            self.client.post(reverse('accounts:mailboxes_create'), payload, follow=True)
        quotas = set(Mailbox.objects.values_list('quota_bytes', flat=True))
        self.assertEqual(quotas, {DEFAULT_QUOTA_BYTES})

    def test_the_page_shows_the_space_budget(self) -> None:
        gb = 1024 * 1024 * 1024
        with patch(
            'backend.apps.mail.services.quota._disk_usage',
            return_value=(10 * gb, 6 * gb),
        ):
            Mailbox.objects.create(domain=Domain.objects.get(), local_part='a', quota_bytes=4 * gb)
            response = self.client.get(reverse('accounts:mailboxes'))
        self.assertContains(response, 'Disk free')
        self.assertContains(response, 'Left to allocate')
        # 6 free minus the 4 promised (nothing stored) = 2 left to allocate.
        self.assertContains(response, '2.0 GB')
        # The quota inputs carry the live-budget hint payload.
        self.assertContains(response, 'data-quota-hint="mb-quota"')
        self.assertContains(response, 'data-headroom-mb="2048"')

    def test_overcommitting_a_quota_warns_but_is_allowed(self) -> None:
        gb = 1024 * 1024 * 1024
        with patch(
            'backend.apps.mail.services.quota._disk_usage',
            return_value=(2 * gb, 1 * gb),
        ):
            response = self.client.post(
                reverse('accounts:mailboxes_create'),
                {'local_part': 'big', 'domain': 'ifinmail.test', 'quota_mb': str(4 * 1024)},
                follow=True,
            )
        self.assertTrue(Mailbox.objects.filter(local_part='big').exists())
        self.assertContains(response, 'promise')
        self.assertContains(response, 'mail volume')

    def test_setting_a_quota_within_budget_does_not_warn(self) -> None:
        gb = 1024 * 1024 * 1024
        with patch(
            'backend.apps.mail.services.quota._disk_usage',
            return_value=(100 * gb, 90 * gb),
        ):
            Mailbox.objects.create(domain=Domain.objects.get(), local_part='a')
            response = self.client.post(
                reverse('accounts:mailboxes_action'),
                {'action': 'quota', 'address': 'a@ifinmail.test', 'quota_mb': '1024'},
                follow=True,
            )
        self.assertNotContains(response, 'promise')

    def test_a_name_with_an_at_sign_is_rejected(self) -> None:
        response = self.client.post(
            reverse('accounts:mailboxes_create'),
            {'local_part': 'hhh@jihu', 'domain': 'ifinmail.test'},
            follow=True,
        )
        self.assertContains(response, 'letters, numbers')
        self.assertFalse(Mailbox.objects.exists())

    def test_a_name_is_trimmed_and_lowercased(self) -> None:
        response = self.client.post(
            reverse('accounts:mailboxes_create'),
            {'local_part': '  Alice  ', 'domain': 'IFINMAIL.TEST'},
            follow=True,
        )
        self.assertContains(response, 'Created alice@ifinmail.test')
        self.assertTrue(Mailbox.objects.filter(local_part='alice').exists())

    def test_you_cannot_delete_or_disable_yourself(self) -> None:
        Mailbox.objects.create(domain=Domain.objects.get(), local_part='root')
        act = reverse('accounts:mailboxes_action')
        for action in ('delete', 'disable'):
            response = self.client.post(
                act, {'action': action, 'address': self.admin.email}, follow=True
            )
            self.assertContains(response, 'your own account')
        self.assertTrue(MailUser.objects.filter(email=self.admin.email, is_active=True).exists())

    def test_setting_your_own_password_via_setup_link_keeps_you_signed_in(self) -> None:
        Mailbox.objects.create(domain=Domain.objects.get(), local_part='root')
        from backend.apps.mail.services import MailboxInviteService

        uid, token = MailboxInviteService.make_token(self.admin.email)
        setup = reverse('accounts:mailbox_setup', kwargs={'uidb64': uid, 'token': token})
        self.client.post(
            setup,
            {'password': 'Brand-New-Pass-5', 'password2': 'Brand-New-Pass-5'},
            follow=True,
        )
        self.assertEqual(self.client.get(reverse('accounts:mailboxes')).status_code, 200)
        self.assertTrue(authenticate(username=self.admin.email, password='Brand-New-Pass-5'))

    def test_an_invalid_setup_link_is_rejected(self) -> None:
        MailboxService.create('ifinmail.test', 'alice', None)
        bad = reverse('accounts:mailbox_setup', kwargs={'uidb64': 'bad', 'token': 'bad-token'})
        response = self.client.get(bad)
        self.assertContains(response, 'Invalid setup link')
        self.assertIsNone(authenticate(username='alice@ifinmail.test', password='x'))

    def test_mailbox_page_lists_domains_and_rows(self) -> None:
        MailboxService.create('ifinmail.test', 'alice', GOOD)
        html = self.client.get(reverse('accounts:mailboxes')).content.decode()
        self.assertIn('alice@ifinmail.test', html)
        self.assertIn('@ifinmail.test</option>', html)
        self.assertIn('aria-current="page"', html)

    def test_manage_opens_a_modal_not_inline_forms(self) -> None:
        MailboxService.create('ifinmail.test', 'alice', GOOD)
        html = self.client.get(reverse('accounts:mailboxes')).content.decode()
        self.assertIn('id="mailbox-manage-modal"', html)
        self.assertIn('data-action="open-manage-mailbox"', html)
        self.assertIn('data-address="alice@ifinmail.test"', html)
        self.assertNotIn('<details', html)
        self.assertNotIn('mailbox_row', html)

    def test_aliases_can_be_created_and_removed(self) -> None:
        response = self.client.post(
            reverse('accounts:aliases_create'),
            {'local_part': 'sales', 'domain': 'ifinmail.test', 'destination': 'me@example.org'},
            follow=True,
        )
        self.assertContains(response, 'now forwards to me@example.org')
        alias = Alias.objects.get()
        response = self.client.post(
            reverse('accounts:aliases_delete'), {'alias_id': str(alias.pk)}, follow=True
        )
        self.assertContains(response, 'Alias removed')
        self.assertFalse(Alias.objects.exists())

    def test_registration_toggle_is_persisted_and_audited(self) -> None:
        self.assertFalse(registration_open())
        self.client.post(reverse('accounts:registration_toggle'), {'open': 'on'})
        self.assertTrue(registration_open())
        self.client.post(reverse('accounts:registration_toggle'), {})
        self.assertFalse(registration_open())


class RegistrationIdentityTests(_Base):
    """A self-registered person must end up able to sign in to the mailbox they chose."""

    def setUp(self) -> None:
        super().setUp()
        self.make_domain(verified=True)

    def _register(self, contact: str, username: str, password: str = GOOD) -> None:
        self.client.post(reverse('accounts:reg_profile'), {'email': contact})
        self.client.post(
            reverse('accounts:reg_password'), {'password': password, 'password2': password}
        )
        user = MailUser.objects.get(email=contact)
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        self.client.get(
            reverse(
                'accounts:reg_verify_confirm',
                kwargs={'uidb64': uid, 'token': token_generator.make_token(user)},
            )
        )
        self.client.post(reverse('accounts:reg_username'), {'username': username})

    def test_registration_is_closed_by_default(self) -> None:
        response = self.client.get(reverse('accounts:reg_profile'))
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, 'Registration is closed', status_code=403)
        self.assertNotContains(
            self.client.get(reverse('accounts:login')), reverse('accounts:reg_profile')
        )
        self.assertFalse(MailUser.objects.exists())

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_registered_person_can_sign_in_to_their_new_address(self) -> None:
        set_registration_open(True)
        self.assertContains(
            self.client.get(reverse('accounts:login')), reverse('accounts:reg_profile')
        )
        self._register('person@gmail.example', 'person')
        self.assertTrue(
            Mailbox.objects.filter(local_part='person', domain__name='ifinmail.test').exists()
        )
        self.assertFalse(MailUser.objects.filter(email='person@gmail.example').exists())
        user = authenticate(username='person@ifinmail.test', password=GOOD)
        self.assertIsNotNone(user)
        # Dovecot's passdb row matches the mailbox address and carries a usable hash.
        self.assertTrue(user.password_hash.startswith('$6$'))
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_a_name_that_is_taken_or_reserved_cannot_be_claimed(self) -> None:
        set_registration_open(True)
        Mailbox.objects.create(domain=Domain.objects.get(), local_part='finance')  # login-less
        for name in ('finance', 'postmaster', 'admin'):
            self.client.logout()
            self._register(f'{name}@ext.example', name)
            self.assertFalse(
                MailUser.objects.filter(email=f'{name}@ifinmail.test').exists(), msg=name
            )
        self.assertEqual(Mailbox.objects.count(), 1)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_username_availability_uses_the_real_address_space(self) -> None:
        set_registration_open(True)
        MailboxService.create('ifinmail.test', 'taken', GOOD)
        url = reverse('accounts:reg_check_username')
        self.assertFalse(
            json.loads(self.client.get(url, {'username': 'taken'}).content)['available']
        )
        self.assertFalse(
            json.loads(self.client.get(url, {'username': 'admin'}).content)['available']
        )
        self.assertTrue(
            json.loads(self.client.get(url, {'username': 'fresh-name'}).content)['available']
        )
