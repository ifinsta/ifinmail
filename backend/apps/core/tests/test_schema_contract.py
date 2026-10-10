"""The SQL that creates the mail tables must cover every column the models map.

The models are ``managed = False`` and their migrations only update Django's
state, so a column missing from init-db.sh / db-upgrade.sql is never created and
every query on that model fails in production ("column does not exist").
"""

from __future__ import annotations

import re
from pathlib import Path

from django.apps import apps
from django.test import SimpleTestCase

DOCKER = Path(__file__).resolve().parents[4] / 'provisioning' / 'docker'


def _sql() -> str:
    return (DOCKER / 'init-db.sh').read_text() + '\n' + (DOCKER / 'db-upgrade.sql').read_text()


class SchemaContractTests(SimpleTestCase):
    def test_every_mapped_column_is_created_by_the_provisioning_sql(self) -> None:
        sql = _sql()
        problems = []
        for model in apps.get_models():
            if model._meta.managed:
                continue
            table = model._meta.db_table
            block = re.search(rf'CREATE TABLE IF NOT EXISTS {table} \((.*?)\n\);', sql, re.S)
            if block is None:
                problems.append(f'{table}: no CREATE TABLE in init-db.sh')
                continue
            alters = ' '.join(
                re.findall(rf'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS (\w+)', sql)
            )
            known = block.group(1) + ' ' + alters
            for field in model._meta.concrete_fields:
                if not re.search(rf'\b{field.column}\b', known):
                    problems.append(f'{table}.{field.column}')
        self.assertEqual(problems, [])

    def test_the_app_role_may_create_foreign_keys_to_existing_tables(self) -> None:
        """Django's admin and axes migrations reference users; without REFERENCES migrate fails."""
        init = (DOCKER / 'init-db.sh').read_text()
        self.assertRegex(init, r'GRANT SELECT, INSERT, UPDATE, DELETE, REFERENCES ON ALL TABLES')
        self.assertIn('REFERENCES', (DOCKER / 'db-upgrade.sql').read_text())

    def test_dovecot_may_read_what_its_quota_query_joins(self) -> None:
        init = (DOCKER / 'init-db.sh').read_text()
        for table in ('users', 'domains', 'mailboxes'):
            self.assertIn(f'GRANT SELECT ON {table} TO dovecot;', init)
