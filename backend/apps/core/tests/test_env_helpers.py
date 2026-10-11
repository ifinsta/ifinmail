"""The shared environment helpers: .env loading and mail-domain precedence."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase

from backend.config.env import load_dotenv, primary_domain


class LoadDotenvTests(SimpleTestCase):
    def test_values_load_and_never_override_the_real_environment(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / '.env'
            path.write_text(
                '# comment\n'
                '\n'
                'NEW_KEY=value\n'
                'EXISTING_KEY=from-file\n'
                'EMPTY_KEY=\n'
                'QUOTED_KEY="quoted value"\n'
                'export EXPORTED_KEY=ok\n',
                encoding='utf-8',
            )
            with patch.dict(os.environ, {'EXISTING_KEY': 'from-env'}, clear=True):
                load_dotenv(path)
                self.assertEqual(os.environ['NEW_KEY'], 'value')
                self.assertEqual(os.environ['EXISTING_KEY'], 'from-env')
                self.assertNotIn('EMPTY_KEY', os.environ)
                self.assertEqual(os.environ['QUOTED_KEY'], 'quoted value')
                self.assertEqual(os.environ['EXPORTED_KEY'], 'ok')

    def test_missing_file_is_not_an_error(self) -> None:
        load_dotenv(Path('definitely') / 'not' / 'here.env')


class PrimaryDomainTests(SimpleTestCase):
    def test_domain_wins_over_mail_domain(self) -> None:
        env = {'DOMAIN': 'primary.example', 'MAIL_DOMAIN': 'secondary.example'}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(primary_domain(), 'primary.example')

    def test_mail_domain_is_used_when_domain_is_unset(self) -> None:
        env = {'DOMAIN': '', 'MAIL_DOMAIN': 'mail.example'}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(primary_domain(), 'mail.example')

    def test_blank_when_neither_is_set(self) -> None:
        with patch.dict(os.environ, {'DOMAIN': '', 'MAIL_DOMAIN': ''}, clear=True):
            self.assertEqual(primary_domain(), '')
