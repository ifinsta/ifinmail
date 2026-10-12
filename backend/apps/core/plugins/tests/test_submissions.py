"""Submission state machine: submit, approve, reject, withdraw, retire; publishing rules."""

from __future__ import annotations

from unittest.mock import patch

from backend.apps.core.platform.services.audit import AuditService
from backend.apps.core.plugins.services import CatalogService, SubmissionService, registry
from backend.apps.core.plugins.services import manifest as manifests
from backend.apps.core.plugins.tests.helpers import text
from backend.apps.core.plugins.types import (
    ManifestError,
    NotFoundError,
    PluginError,
    PluginSource,
    SubmissionState,
    TransitionError,
)
from backend.apps.core.tests.mail_base import MailTablesTestCase

DEV, REVIEWER = 'dev@ifinmail.test', 'admin@ifinmail.test'


class SubmissionTests(MailTablesTestCase):
    def submit(self, **changes: object):
        return SubmissionService.submit(text(**changes), DEV, 'please review')

    def test_submit_then_approve_publishes_it(self) -> None:
        row = self.submit()
        self.assertEqual(row.state, SubmissionState.SUBMITTED)
        self.assertEqual(
            (row.plugin_id, row.version, row.submitter_note),
            ('test-journal', '1.0.0', 'please review'),
        )
        self.assertIsNone(CatalogService.get('test-journal'))  # never visible before approval
        self.assertEqual(SubmissionService.pending_count(), 1)
        approved = SubmissionService.approve(str(row.id), REVIEWER, 'looks good')
        self.assertEqual(approved.state, SubmissionState.APPROVED)
        self.assertEqual((approved.reviewed_by, approved.review_note), (REVIEWER, 'looks good'))
        self.assertIsNotNone(approved.reviewed_at)
        entry = CatalogService.get('test-journal')
        self.assertEqual((entry.source, entry.submission_id), (PluginSource.SUBMITTED, str(row.id)))
        self.assertTrue(AuditService.has('plugin_submitted'))
        self.assertTrue(AuditService.has('plugin_submission_approve'))

    def test_nothing_is_approved_without_an_explicit_action(self) -> None:
        row = self.submit()
        self.assertEqual(SubmissionService.get(str(row.id)).state, SubmissionState.SUBMITTED)
        self.assertEqual(CatalogService.entries(), list(CatalogService.bundled()))

    def test_transitions_are_one_way(self) -> None:
        row = self.submit()
        SubmissionService.approve(str(row.id), REVIEWER)
        for action in (SubmissionService.approve, SubmissionService.reject):
            with self.assertRaises(TransitionError):
                action(str(row.id), REVIEWER, 'x')
        with self.assertRaises(TransitionError):
            SubmissionService.withdraw(str(row.id), DEV, is_reviewer=False)
        SubmissionService.retire(str(row.id), REVIEWER)
        with self.assertRaises(TransitionError):
            SubmissionService.retire(str(row.id), REVIEWER)
        self.assertIsNone(CatalogService.get('test-journal'))

    def test_reject_needs_a_note_and_the_version_can_be_resubmitted(self) -> None:
        row = self.submit()
        with self.assertRaises(PluginError):
            SubmissionService.reject(str(row.id), REVIEWER, '  ')
        SubmissionService.reject(str(row.id), REVIEWER, 'Explain the retention impact.')
        again = self.submit()  # same id and version after a rejection
        self.assertNotEqual(again.id, row.id)

    def test_only_the_submitter_or_a_reviewer_can_withdraw(self) -> None:
        row = self.submit()
        with self.assertRaises(PluginError):
            SubmissionService.withdraw(str(row.id), 'someone@ifinmail.test', is_reviewer=False)
        SubmissionService.withdraw(str(row.id), DEV, is_reviewer=False)
        self.assertEqual(SubmissionService.get(str(row.id)).state, SubmissionState.WITHDRAWN)
        other = self.submit()
        SubmissionService.withdraw(str(other.id), REVIEWER, is_reviewer=True)

    def test_publishing_rules(self) -> None:
        with self.assertRaisesMessage(PluginError, 'built-in plugin'):
            self.submit(plugin__id='compliance-journal')
        row = self.submit()
        with self.assertRaisesMessage(PluginError, 'already submitted'):
            self.submit()
        SubmissionService.approve(str(row.id), REVIEWER)
        with self.assertRaisesMessage(PluginError, 'already submitted or published'):
            self.submit()
        with self.assertRaisesMessage(PluginError, 'not newer'):
            self.submit(plugin__version='0.9.0')
        newer = self.submit(plugin__version='1.0.1')
        SubmissionService.approve(str(newer.id), REVIEWER)
        self.assertEqual(CatalogService.get('test-journal').manifest.version, '1.0.1')

    def test_an_invalid_manifest_is_refused_with_every_problem(self) -> None:
        with self.assertRaises(ManifestError) as caught:
            SubmissionService.submit(text(plugin__id='X', plugin__category='fun'), DEV)
        self.assertGreaterEqual(len(caught.exception.problems), 2)

    def test_approval_validates_again_against_todays_core(self) -> None:
        row = self.submit()
        manifests._load_cached.cache_clear()
        with patch.object(registry, '_capabilities', {}), self.assertRaises(ManifestError):
            SubmissionService.approve(str(row.id), REVIEWER)
        manifests._load_cached.cache_clear()
        self.assertEqual(SubmissionService.get(str(row.id)).state, SubmissionState.SUBMITTED)

    def test_unknown_or_malformed_ids(self) -> None:
        for value in ('nope', '', '00000000-0000-0000-0000-000000000000', None):
            with self.subTest(value=value), self.assertRaises(NotFoundError):
                SubmissionService.get(value)
        with self.assertRaises(NotFoundError):
            SubmissionService.approve('nope', REVIEWER)

    def test_notes_are_trimmed_and_capped(self) -> None:
        row = SubmissionService.submit(text(), DEV, '  ' + 'n' * 3000)
        self.assertEqual(len(row.submitter_note), 2000)
