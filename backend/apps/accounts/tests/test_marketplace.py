"""Marketplace pages: browsing, the install journey, submissions and permissions."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from backend.apps.accounts.models import MailUser
from backend.apps.accounts.services.roles import RoleService
from backend.apps.accounts.services.setup_state import SetupState
from backend.apps.core.plugins.models import PluginInstallation, PluginSubmission
from backend.apps.core.plugins.tests.helpers import text
from backend.apps.core.plugins.types import InstallationState, SubmissionState
from backend.apps.core.tests.mail_base import MailTablesTestCase
from backend.apps.mail.models import Mailbox

GOOD = 'Correct-Horse-9'
JOURNAL = 'compliance-journal'


class _Base(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        SetupState.mark_complete()
        RoleService.ensure_seed()
        self.status_dir = os.path.join(self.tmp, 'status')
        os.makedirs(self.status_dir)
        patcher = patch.dict(os.environ, {'IFINMAIL_STATUS_DIR': self.status_dir})
        patcher.start()
        self.addCleanup(patcher.stop)
        domain = self.make_domain()
        Mailbox.objects.create(domain=domain, local_part='journal')
        self.admin = self.login('root@ifinmail.test', superuser=True)

    def login(self, email: str, *, superuser: bool = False, role: str | None = None) -> MailUser:
        user = MailUser.objects.create_user(email, GOOD, is_staff=True, is_superuser=superuser)
        if role:
            RoleService.assign(user, role)
        self.client.force_login(user, backend='django.contrib.auth.backends.ModelBackend')
        session = self.client.session
        session['mfa_verified_at'] = timezone.now().isoformat()
        session.save()
        return user

    def act(self, action: str, plugin_id: str = JOURNAL, follow: bool = True, **fields: str):
        row = PluginInstallation.objects.filter(plugin_id=plugin_id).first()
        data = {'action': action, **fields}
        if row is not None:
            data.setdefault('revision', str(row.revision))
        return self.client.post(
            reverse('accounts:marketplace_plugin_action', kwargs={'plugin_id': plugin_id}),
            data,
            follow=follow,
        )

    def bcc(self) -> str:
        path = Path(self.runtime_dir) / 'postfix-plugins.conf'
        for line in path.read_text().splitlines():
            if line.startswith('always_bcc'):
                return line.partition('=')[2].strip()
        return ''


class BrowseTests(_Base):
    def test_sidebar_links_to_the_marketplace_next_to_settings(self) -> None:
        html = self.client.get(reverse('accounts:dashboard')).content.decode()
        settings_at = html.index(reverse('accounts:settings'))
        market_at = html.index(reverse('accounts:marketplace'))
        self.assertGreater(market_at, settings_at)
        self.assertNotIn(reverse('accounts:dashboard'), html[settings_at:market_at])

    def test_discover_lists_the_built_in_plugin(self) -> None:
        response = self.client.get(reverse('accounts:marketplace'))
        self.assertContains(response, 'Compliance journal')
        self.assertContains(
            response, reverse('accounts:marketplace_plugin', kwargs={'plugin_id': JOURNAL})
        )
        self.assertContains(response, 'aria-current="page"', count=2)  # sidebar item and tab

    def test_every_tab_and_unknown_tabs(self) -> None:
        for tab in ('discover', 'installed', 'submissions', 'nonsense'):
            with self.subTest(tab=tab):
                self.assertEqual(
                    self.client.get(reverse('accounts:marketplace'), {'tab': tab}).status_code, 200
                )
        self.assertContains(
            self.client.get(reverse('accounts:marketplace'), {'tab': 'installed'}),
            'Nothing installed yet',
        )

    def test_plugin_page_explains_what_it_changes(self) -> None:
        response = self.client.get(
            reverse('accounts:marketplace_plugin', kwargs={'plugin_id': JOURNAL})
        )
        self.assertContains(response, 'always_bcc')
        self.assertContains(response, 'Send a copy of every message')
        self.assertContains(response, 'Install and enable')
        self.assertContains(response, 'Not installed')

    def test_unknown_plugin_is_404(self) -> None:
        url = reverse('accounts:marketplace_plugin', kwargs={'plugin_id': 'no-such-plugin'})
        self.assertEqual(self.client.get(url).status_code, 404)


class InstallJourneyTests(_Base):
    def test_install_configure_disable_enable_uninstall(self) -> None:
        response = self.act('install', setting__archive_address='journal@ifinmail.test')
        self.assertContains(response, 'installed and enabled')
        self.assertEqual(PluginInstallation.objects.get().state, InstallationState.ENABLED)
        self.assertEqual(self.bcc(), 'journal@ifinmail.test')
        self.assertContains(response, 'Save settings')
        self.assertContains(response, 'Disable')

        response = self.act('disable')
        self.assertContains(response, 'disabled')
        self.assertEqual(self.bcc(), '')
        response = self.act('enable')
        self.assertEqual(self.bcc(), 'journal@ifinmail.test')

        response = self.act('uninstall')
        self.assertRedirects(response, reverse('accounts:marketplace') + '?tab=installed')
        self.assertContains(response, 'uninstalled')
        self.assertFalse(PluginInstallation.objects.exists())
        self.assertEqual(self.bcc(), '')

    def test_bad_settings_show_on_the_field_and_keep_the_input(self) -> None:
        response = self.act(
            'install', follow=False, setting__archive_address='nobody@ifinmail.test'
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'not a mailbox on this server', status_code=400)
        self.assertContains(response, 'value="nobody@ifinmail.test"', status_code=400)
        self.assertContains(response, 'aria-invalid="true"', status_code=400)
        self.assertFalse(PluginInstallation.objects.exists())

    def test_a_stale_form_is_refused_with_a_reload_hint(self) -> None:
        self.act('install', setting__archive_address='journal@ifinmail.test')
        old = PluginInstallation.objects.get().revision
        self.act('disable')
        response = self.act('enable', revision=str(old))
        self.assertContains(response, 'Reload the page')
        self.assertEqual(PluginInstallation.objects.get().state, InstallationState.DISABLED)

    def test_a_repeated_post_is_refused_not_repeated(self) -> None:
        self.act('install', setting__archive_address='journal@ifinmail.test')
        response = self.act('install', setting__archive_address='journal@ifinmail.test')
        self.assertContains(response, 'Cannot install')
        self.assertEqual(PluginInstallation.objects.count(), 1)

    def test_garbage_actions_and_get_on_the_action_url(self) -> None:
        response = self.act('explode')
        self.assertContains(response, 'could not be read')
        url = reverse('accounts:marketplace_plugin_action', kwargs={'plugin_id': JOURNAL})
        self.assertNotEqual(self.client.get(url, HTTP_ACCEPT='text/html').status_code, 500)

    def test_installed_tab_and_health_report_the_plugin(self) -> None:
        self.act('install', setting__archive_address='journal@ifinmail.test')
        response = self.client.get(reverse('accounts:marketplace'), {'tab': 'installed'})
        self.assertContains(response, 'Compliance journal')
        self.assertContains(response, 'Enabled')
        from backend.apps.accounts.services import system_health as sh

        checks = sh._plugins()
        self.assertEqual(checks[0].state, sh.OK)
        PluginInstallation.objects.update(state=InstallationState.FAILED, last_error='boom')
        self.assertEqual(sh._plugins()[0].state, sh.ERROR)
        self.assertContains(
            self.client.get(reverse('accounts:marketplace_plugin', kwargs={'plugin_id': JOURNAL})),
            'The last change failed',
        )


class PermissionTests(_Base):
    def test_support_role_can_browse_but_not_change_or_review(self) -> None:
        self.client.logout()
        self.login('support@ifinmail.test', role='support')
        page = self.client.get(
            reverse('accounts:marketplace_plugin', kwargs={'plugin_id': JOURNAL})
        )
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'Install and enable')
        self.assertContains(page, 'needs the system.manage permission')
        self.assertEqual(
            self.act(
                'install', follow=False, setting__archive_address='journal@ifinmail.test'
            ).status_code,
            403,
        )
        self.assertFalse(PluginInstallation.objects.exists())

    def test_anonymous_and_non_staff_are_sent_to_sign_in(self) -> None:
        self.client.logout()
        for name, kwargs in (
            ('accounts:marketplace', {}),
            ('accounts:marketplace_submit', {}),
            ('accounts:marketplace_plugin', {'plugin_id': JOURNAL}),
        ):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name, kwargs=kwargs)).status_code, 302)


class SubmissionFlowTests(_Base):
    def test_submit_review_and_install_a_plugin(self) -> None:
        self.client.logout()
        dev = self.login('dev@ifinmail.test', role='support')
        response = self.client.post(
            reverse('accounts:marketplace_submit'),
            {'manifest': text(), 'note': 'for audits'},
            follow=True,
        )
        self.assertContains(response, 'A reviewer must approve it')
        row = PluginSubmission.objects.get()
        self.assertEqual((row.state, row.submitted_by), (SubmissionState.SUBMITTED, dev.email))
        # The developer cannot approve.
        url = reverse('accounts:marketplace_submission_action', kwargs={'submission_id': row.id})
        self.assertEqual(self.client.post(url, {'action': 'approve'}).status_code, 403)
        page = self.client.get(
            reverse('accounts:marketplace_submission', kwargs={'submission_id': row.id})
        )
        self.assertContains(page, 'Withdraw')
        self.assertNotContains(page, 'Approve and publish')
        # A reviewer approves; the plugin appears and installs like any other.
        self.client.logout()
        self.login('reviewer@ifinmail.test', superuser=True)
        page = self.client.get(
            reverse('accounts:marketplace_submission', kwargs={'submission_id': row.id})
        )
        self.assertContains(page, 'Approve and publish')
        self.assertContains(page, 'always_bcc')
        self.assertContains(page, '[plugin]')  # raw manifest shown, escaped
        response = self.client.post(url, {'action': 'approve', 'note': 'ok'}, follow=True)
        self.assertContains(response, 'is now in the Marketplace')
        self.assertContains(self.client.get(reverse('accounts:marketplace')), 'Test journal')
        response = self.act(
            'install', plugin_id='test-journal', setting__archive_address='journal@ifinmail.test'
        )
        self.assertContains(response, 'installed and enabled')

    def test_invalid_manifests_list_every_problem(self) -> None:
        response = self.client.post(
            reverse('accounts:marketplace_submit'),
            {'manifest': text(plugin__id='X', plugin__category='fun')},
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'plugin.id', status_code=400)
        self.assertContains(response, 'plugin.category', status_code=400)
        self.assertFalse(PluginSubmission.objects.exists())
        response = self.client.post(reverse('accounts:marketplace_submit'), {'manifest': ''})
        self.assertContains(response, 'Paste a plugin.toml', status_code=400)

    def test_upload_a_file_and_reject_with_a_note(self) -> None:
        upload = SimpleUploadedFile('plugin.toml', text().encode(), content_type='text/plain')
        self.client.post(reverse('accounts:marketplace_submit'), {'manifest_file': upload})
        row = PluginSubmission.objects.get()
        url = reverse('accounts:marketplace_submission_action', kwargs={'submission_id': row.id})
        response = self.client.post(url, {'action': 'reject'}, follow=True)
        self.assertContains(response, 'Say why it is rejected')
        response = self.client.post(
            url, {'action': 'reject', 'note': 'Add a description.'}, follow=True
        )
        self.assertContains(response, 'rejected')
        self.assertContains(response, 'Add a description.')

    def test_script_in_a_manifest_is_shown_as_text(self) -> None:
        evil = text(plugin__summary='<script>alert(1)</script>')
        self.client.post(reverse('accounts:marketplace_submit'), {'manifest': evil})
        row = PluginSubmission.objects.get()
        page = self.client.get(
            reverse('accounts:marketplace_submission', kwargs={'submission_id': row.id})
        )
        self.assertNotContains(page, '<script>alert(1)</script>')
        self.assertContains(page, '&lt;script&gt;alert(1)&lt;/script&gt;')

    def test_unknown_submission_is_404(self) -> None:
        url = reverse(
            'accounts:marketplace_submission',
            kwargs={'submission_id': '00000000-0000-0000-0000-000000000000'},
        )
        self.assertEqual(self.client.get(url).status_code, 404)
