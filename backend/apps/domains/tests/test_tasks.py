"""The scheduled jobs run, and every scheduled task name exists."""

from __future__ import annotations

import os
from unittest.mock import patch

from django.core import mail
from django.core.cache import cache
from django.test import override_settings

from backend.apps.core.platform.services.runtime import read_runtime_file
from backend.apps.core.tasks import check_certificate_expiry
from backend.apps.core.tests.mail_base import MailTablesTestCase
from backend.apps.domains.services.dkim import DKIMService
from backend.apps.domains.tasks import sync_certificate_hosts, sync_dkim_files, verify_all_domains
from backend.apps.mail.tasks import apply_postfix_overrides


class ScheduleTests(MailTablesTestCase):
    def test_every_scheduled_task_is_registered(self) -> None:
        from backend.config.celery import app

        app.loader.import_default_modules()
        for name, entry in app.conf.beat_schedule.items():
            self.assertIn(entry['task'], app.tasks, msg=name)

    def test_domain_jobs(self) -> None:
        domain = self.make_domain()
        DKIMService.ensure(domain)
        DKIMService.key_path(domain.name, 'default').unlink()
        self.assertEqual(sync_dkim_files(), 1)
        self.assertEqual(sync_certificate_hosts(), 5)
        self.assertIn('mta-sts.ifinmail.test', read_runtime_file('cert-hosts.txt'))
        with patch(
            'backend.apps.domains.services.verification._lookup',
            return_value=['10 mail.ifinmail.test'],
        ):
            self.assertEqual(verify_all_domains(), {'ifinmail.test': True})
        self.assertTrue(apply_postfix_overrides() >= 3)
        self.assertIn('hopcount_limit', read_runtime_file('postfix-overrides.conf'))


_LOCMEM = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}


@override_settings(CACHES=_LOCMEM)
class CertificateExpiryTests(MailTablesTestCase):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    def test_warns_the_administrator_once_when_expiry_is_near(self) -> None:
        with patch(
            'backend.apps.core.platform.services.monitoring.MonitoringService.check_tls_expiry',
            return_value={'days': 9, 'status': 'warn'},
        ):
            check_certificate_expiry()
            check_certificate_expiry()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [os.environ['ADMIN_EMAIL']])

    def test_no_email_when_the_certificate_is_healthy(self) -> None:
        with patch(
            'backend.apps.core.platform.services.monitoring.MonitoringService.check_tls_expiry',
            return_value={'days': 60, 'status': 'ok'},
        ):
            check_certificate_expiry()
        self.assertEqual(len(mail.outbox), 0)
