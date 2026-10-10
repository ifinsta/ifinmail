"""Shared base for tests that touch the mail tables.

``domains``, ``users``, ``mailboxes``, ``aliases``, ``dkim_keys`` and
``dns_provider_config`` are created by init-db.sh in production (the models are
``managed = False``), so tests create them in the throwaway test database.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from unittest.mock import patch

from django.db import connection
from django.test import TransactionTestCase

from backend.apps.accounts.models import MailUser
from backend.apps.dns.models import DNSProviderConfig
from backend.apps.domains.models import DKIMKey, Domain
from backend.apps.mail.models import Alias, Mailbox

UNMANAGED = (Domain, DKIMKey, MailUser, Mailbox, Alias, DNSProviderConfig)


def _create(model: type) -> None:
    with (
        patch.object(model._meta, 'managed', True),
        connection.schema_editor(atomic=False) as editor,
    ):
        editor.create_model(model)


def _drop(model: type) -> None:
    with (
        patch.object(model._meta, 'managed', True),
        connection.schema_editor(atomic=False) as editor,
    ):
        editor.delete_model(model)


class MailTablesTestCase(TransactionTestCase):
    """TransactionTestCase with the mail tables, private key/runtime dirs and a fixed env."""

    env: dict[str, str] = {}

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        for model in UNMANAGED:
            _create(model)

    @classmethod
    def tearDownClass(cls) -> None:
        for model in reversed(UNMANAGED):
            _drop(model)
        super().tearDownClass()

    def setUp(self) -> None:
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix='ifinmail-test-')
        self.dkim_dir = os.path.join(self.tmp, 'dkim')
        self.runtime_dir = os.path.join(self.tmp, 'runtime')
        env = {
            'DKIM_KEY_DIR': self.dkim_dir,
            'IFINMAIL_RUNTIME_DIR': self.runtime_dir,
            'MAIL_HOSTNAME': 'mail.ifinmail.test',
            'DKIM_SELECTOR': 'default',
            'ADMIN_EMAIL': 'admin@ifinmail.test',
            'DOMAIN': 'ifinmail.test',
            'MAIL_DOMAIN': 'ifinmail.test',
            **self.env,
        }
        patcher = patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def tearDown(self) -> None:
        # Django's flush skips unmanaged tables, so clear them ourselves.
        for model in reversed(UNMANAGED):
            model.objects.all().delete()
        super().tearDown()

    def make_domain(self, name: str = 'ifinmail.test', *, verified: bool = False) -> Domain:
        return Domain.objects.create(name=name, verified=verified)
