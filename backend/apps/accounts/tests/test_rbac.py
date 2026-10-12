"""Neutral RBAC: seed roles, effective permissions, gates, assignment guards."""

from __future__ import annotations

from django.urls import reverse
from django.utils import timezone

from backend.apps.accounts.models import MailUser
from backend.apps.accounts.services.roles import RoleError, RoleService
from backend.apps.accounts.types.permissions import ALL_PERMISSIONS, PermissionCode
from backend.apps.core.tests.mail_base import MailTablesTestCase
from backend.apps.domains.models import Domain
from backend.apps.mail.models import Mailbox

GOOD = 'Correct-Horse-9'
MODEL_BACKEND = 'django.contrib.auth.backends.ModelBackend'


def _verified_session(client) -> None:
    session = client.session
    session['mfa_verified_at'] = timezone.now().isoformat()
    session.save()


class RoleModelTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        RoleService.ensure_seed()

    def test_seed_roles_exist_with_sane_codes(self) -> None:
        seeded = {role.key: role for role in RoleService.list_roles()}
        self.assertEqual(set(seeded), {'owner', 'administrator', 'support'})
        self.assertEqual(set(seeded['owner'].permissions), set(ALL_PERMISSIONS))
        self.assertNotIn('roles.manage', seeded['administrator'].permissions)
        self.assertEqual(set(seeded['support'].permissions), {'console.access', 'audit.view'})
        for role in seeded.values():
            self.assertTrue(role.is_system)
            for code in role.permissions:
                self.assertIn(code, ALL_PERMISSIONS)


class EffectivePermissionTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        RoleService.ensure_seed()

    def test_matrix(self) -> None:
        admin = MailUser.objects.create_user(
            'root@ifinmail.test', GOOD, is_staff=True, is_superuser=True
        )
        staff = MailUser.objects.create_user('ops@ifinmail.test', GOOD, is_staff=True)
        plain = MailUser.objects.create_user('plain@ifinmail.test', GOOD)
        self.assertEqual(RoleService.effective_permissions(admin), set(ALL_PERMISSIONS))
        # Legacy staff (no role): today's behavior, unchanged.
        self.assertEqual(RoleService.effective_permissions(staff), set(ALL_PERMISSIONS))
        self.assertEqual(RoleService.effective_permissions(plain), set())
        inactive = MailUser.objects.create_user(
            'off@ifinmail.test', GOOD, is_staff=True, is_active=False
        )
        self.assertEqual(RoleService.effective_permissions(inactive), set())

    def test_named_role_narrows(self) -> None:
        MailUser.objects.create_user('root@ifinmail.test', GOOD, is_staff=True, is_superuser=True)
        staff = MailUser.objects.create_user('ops@ifinmail.test', GOOD, is_staff=True)
        RoleService.assign(staff, 'support')
        perms = RoleService.effective_permissions(staff)
        self.assertEqual(perms, {'console.access', 'audit.view'})
        self.assertTrue(RoleService.has_perm(staff, PermissionCode.AUDIT_VIEW))
        self.assertFalse(RoleService.has_perm(staff, PermissionCode.MAIL_MANAGE))

    def test_unknown_role_is_refused_and_clear_restores_legacy(self) -> None:
        MailUser.objects.create_user('root@ifinmail.test', GOOD, is_staff=True, is_superuser=True)
        staff = MailUser.objects.create_user('ops@ifinmail.test', GOOD, is_staff=True)
        with self.assertRaises(RoleError):
            RoleService.assign(staff, 'nope')
        RoleService.assign(staff, 'support')
        RoleService.assign(staff, None)
        self.assertEqual(RoleService.effective_permissions(staff), set(ALL_PERMISSIONS))

    def test_last_role_granter_is_protected(self) -> None:
        first = MailUser.objects.create_user('a@ifinmail.test', GOOD, is_staff=True)
        second = MailUser.objects.create_user('b@ifinmail.test', GOOD, is_staff=True)
        # Both legacy holders: narrowing one is fine.
        RoleService.assign(first, 'support')
        self.assertEqual(RoleService.effective_permissions(second), set(ALL_PERMISSIONS))
        # Second is now the last holder: narrowing them is refused.
        with self.assertRaises(RoleError):
            RoleService.assign(second, 'support')
        # ...unless someone else can still grant roles.
        RoleService.assign(second, 'owner')
        RoleService.assign(first, 'support')


class RoleGateTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        RoleService.ensure_seed()
        MailUser.objects.create_user('root@ifinmail.test', GOOD, is_staff=True, is_superuser=True)
        self.support = MailUser.objects.create_user('sup@ifinmail.test', GOOD, is_staff=True)
        RoleService.assign(self.support, 'support')
        self.client.force_login(self.support, backend=MODEL_BACKEND)
        _verified_session(self.client)

    def test_support_reads_dashboard_and_logs_but_not_mailboxes(self) -> None:
        self.assertEqual(self.client.get(reverse('accounts:dashboard')).status_code, 200)
        self.assertEqual(self.client.get(reverse('accounts:logs')).status_code, 200)
        self.assertEqual(self.client.get(reverse('accounts:mailboxes')).status_code, 403)
        self.assertEqual(self.client.get(reverse('dns:server')).status_code, 403)

    def test_outsiders_keep_the_sign_in_redirect(self) -> None:
        self.client.logout()
        for name in ('accounts:dashboard', 'accounts:mailboxes', 'dns:server'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 302)


class RoleAssignmentViewTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        RoleService.ensure_seed()
        Domain.objects.create(name='ifinmail.test')
        self.owner = MailUser.objects.create_user(
            'root@ifinmail.test', GOOD, is_staff=True, is_superuser=True
        )
        self.client.force_login(self.owner, backend=MODEL_BACKEND)
        _verified_session(self.client)

    def _mailbox_id(self, local: str) -> object:
        from backend.apps.mail.services import MailboxService

        mailbox, _ = MailboxService.create('ifinmail.test', local, GOOD)
        return mailbox.id

    def test_assign_and_audit(self) -> None:
        from backend.apps.core.platform.services.audit import AuditService

        mailbox_id = self._mailbox_id('alice')
        response = self.client.post(
            reverse('accounts:mailbox_role_action', kwargs={'mailbox_id': mailbox_id}),
            {'address': 'alice@ifinmail.test', 'role': 'support', 'confirm_password': GOOD},
            follow=True,
        )
        self.assertContains(response, 'is now Support')
        self.assertEqual(MailUser.objects.get(email='alice@ifinmail.test').role.key, 'support')
        self.assertTrue(AuditService.has('role_assigned', detail='alice@ifinmail.test -> support'))

    def test_self_assignment_and_mismatch_are_refused(self) -> None:
        Mailbox.objects.create(domain=Domain.objects.get(), local_part='root')
        root_id = Mailbox.objects.get(local_part='root').id
        response = self.client.post(
            reverse('accounts:mailbox_role_action', kwargs={'mailbox_id': root_id}),
            {'address': 'root@ifinmail.test', 'role': 'support'},
            follow=True,
        )
        self.assertContains(response, 'Your own role cannot be changed here')
        mailbox_id = self._mailbox_id('alice')
        response = self.client.post(
            reverse('accounts:mailbox_role_action', kwargs={'mailbox_id': mailbox_id}),
            {'address': 'someone-else@ifinmail.test', 'role': 'support'},
            follow=True,
        )
        self.assertContains(response, 'does not match this profile')

    def test_without_grant_permission_is_forbidden(self) -> None:
        plain_admin = MailUser.objects.create_user('ops@ifinmail.test', GOOD, is_staff=True)
        RoleService.assign(plain_admin, 'support')
        mailbox_id = self._mailbox_id('alice')
        self.client.force_login(plain_admin, backend=MODEL_BACKEND)
        _verified_session(self.client)
        response = self.client.post(
            reverse('accounts:mailbox_role_action', kwargs={'mailbox_id': mailbox_id}),
            {'address': 'alice@ifinmail.test', 'role': 'support'},
        )
        self.assertEqual(response.status_code, 403)
