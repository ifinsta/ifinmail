"""Manifest parsing and validation: every rule in references/manifest.md."""

from __future__ import annotations

from django.test import SimpleTestCase

from backend.apps.core.plugins.services import manifest as manifests
from backend.apps.core.plugins.services.catalog import CatalogService
from backend.apps.core.plugins.tests.helpers import BASE, manifest, text, to_toml
from backend.apps.core.plugins.types import MAX_MANIFEST_BYTES, ManifestError, SettingsError

S = BASE['settings'][0]


def setting(**changes: object) -> dict:
    return {**S, **changes}


# (case name, manifest data, expected location of the first relevant problem)
INVALID = [
    ('wrong manifest_version', manifest(manifest_version=3), 'manifest_version'),
    ('version 1 named software', manifest(manifest_version=1), 'manifest_version'),
    (
        'point instead of capability',
        manifest(contributes=[{'point': 'postfix.main', 'values': {'always_bcc': 'a@b.test'}}]),
        'contributes[0].point',
    ),
    ('bool manifest_version', manifest(manifest_version=True), 'manifest_version'),
    ('missing manifest_version', manifest(manifest_version=None), 'manifest_version'),
    ('unknown top key', {**manifest(), 'extra': 1}, 'extra'),
    ('missing plugin', manifest(plugin=None), 'plugin'),
    ('unknown plugin key', manifest(plugin__homepage='x'), 'plugin.homepage'),
    ('id missing', manifest(plugin__id=None), 'plugin.id'),
    ('id uppercase', manifest(plugin__id='Test-Journal'), 'plugin.id'),
    ('id too short', manifest(plugin__id='ab'), 'plugin.id'),
    ('id too long', manifest(plugin__id='a' * 41), 'plugin.id'),
    ('id starts with digit', manifest(plugin__id='1abc'), 'plugin.id'),
    ('id double hyphen', manifest(plugin__id='te--st'), 'plugin.id'),
    ('id trailing hyphen', manifest(plugin__id='test-'), 'plugin.id'),
    ('id underscore', manifest(plugin__id='test_journal'), 'plugin.id'),
    ('id not text', manifest(plugin__id=5), 'plugin.id'),
    ('name empty', manifest(plugin__name=''), 'plugin.name'),
    ('name too long', manifest(plugin__name='n' * 61), 'plugin.name'),
    ('name control char', manifest(plugin__name='a\tb'), 'plugin.name'),
    ('version missing', manifest(plugin__version=None), 'plugin.version'),
    ('version two parts', manifest(plugin__version='1.0'), 'plugin.version'),
    ('version leading zero', manifest(plugin__version='01.0.0'), 'plugin.version'),
    ('version prerelease', manifest(plugin__version='1.0.0-beta'), 'plugin.version'),
    ('version v prefix', manifest(plugin__version='v1.0.0'), 'plugin.version'),
    ('version too big', manifest(plugin__version='10000.0.0'), 'plugin.version'),
    ('publisher missing', manifest(plugin__publisher=None), 'plugin.publisher'),
    ('category unknown', manifest(plugin__category='fun'), 'plugin.category'),
    ('summary missing', manifest(plugin__summary=None), 'plugin.summary'),
    ('summary too long', manifest(plugin__summary='s' * 161), 'plugin.summary'),
    ('description too long', manifest(plugin__description='d' * 4001), 'plugin.description'),
    ('description control char', manifest(plugin__description='a\x07b'), 'plugin.description'),
    ('requires_core bad', manifest(plugin__requires_core='latest'), 'plugin.requires_core'),
    ('settings not a list', manifest(settings={'key': 'x'}), 'settings'),
    (
        'too many settings',
        manifest(settings=[setting(key=f'k{i}', type='text', required=False) for i in range(21)]),
        'settings',
    ),
    (
        'setting unknown key',
        manifest(settings=[setting(placeholder='x')]),
        'settings[0].placeholder',
    ),
    (
        'setting key missing',
        manifest(settings=[{k: v for k, v in S.items() if k != 'key'}]),
        'settings[0].key',
    ),
    ('setting key bad', manifest(settings=[setting(key='Archive')]), 'settings[0].key'),
    ('setting key twice', manifest(settings=[S, S]), 'settings[1].key'),
    ('setting type unknown', manifest(settings=[setting(type='colour')]), 'settings[0].type'),
    (
        'setting label missing',
        manifest(settings=[{k: v for k, v in S.items() if k != 'label'}]),
        'settings[0].label',
    ),
    ('setting help too long', manifest(settings=[setting(help='h' * 301)]), 'settings[0].help'),
    ('required not bool', manifest(settings=[setting(required='yes')]), 'settings[0].required'),
    ('min on text', manifest(settings=[setting(key='t', type='text', min=1)]), 'settings[0].min'),
    (
        'min bool',
        manifest(settings=[setting(key='n', type='integer', min=True)]),
        'settings[0].min',
    ),
    (
        'min above max',
        manifest(settings=[setting(key='n', type='integer', min=5, max=1)]),
        'settings[0].min',
    ),
    (
        'choice without options',
        manifest(settings=[setting(key='c', type='choice')]),
        'settings[0].options',
    ),
    (
        'choice empty options',
        manifest(settings=[setting(key='c', type='choice', options=[])]),
        'settings[0].options',
    ),
    (
        'choice duplicate options',
        manifest(settings=[setting(key='c', type='choice', options=['a', 'a'])]),
        'settings[0].options',
    ),
    (
        'options on text',
        manifest(settings=[setting(key='t', type='text', options=['a'])]),
        'settings[0].options',
    ),
    (
        'max_length on email',
        manifest(settings=[setting(key='e', type='email', max_length=5)]),
        'settings[0].max_length',
    ),
    (
        'max_length too big',
        manifest(settings=[setting(key='t', type='text', max_length=501)]),
        'settings[0].max_length',
    ),
    (
        'default wrong type',
        manifest(settings=[setting(key='n', type='integer', default='x')]),
        'settings[0].default',
    ),
    (
        'default out of range',
        manifest(settings=[setting(key='n', type='integer', min=1, max=3, default=9)]),
        'settings[0].default',
    ),
    (
        'default not an option',
        manifest(settings=[setting(key='c', type='choice', options=['a'], default='b')]),
        'settings[0].default',
    ),
    (
        'default bad email',
        manifest(settings=[setting(key='e', type='email', default='nope')]),
        'settings[0].default',
    ),
    ('default on mailbox', manifest(settings=[setting(default='a@b.test')]), 'settings[0].default'),
    ('contributes missing', manifest(contributes=None), 'contributes'),
    ('contributes empty', manifest(contributes=[]), 'contributes'),
    (
        'too many contributions',
        manifest(
            contributes=[{'capability': 'mail.journal', 'values': {'archive_address': 'a@b.test'}}]
            * 11
        ),
        'contributes',
    ),
    (
        'unknown point',
        manifest(contributes=[{'capability': 'nginx.main', 'values': {'x': '1'}}]),
        'contributes[0].capability',
    ),
    (
        'unknown contribution key',
        manifest(
            contributes=[
                {
                    'capability': 'mail.journal',
                    'values': {'archive_address': '{archive_address}'},
                    'when': 'x',
                }
            ]
        ),
        'contributes[0].when',
    ),
    (
        'values empty',
        manifest(contributes=[{'capability': 'mail.journal', 'values': {}}]),
        'contributes[0].values',
    ),
    (
        'key not allowed',
        manifest(
            contributes=[{'capability': 'mail.journal', 'values': {'relayhost': 'smtp.evil.test'}}]
        ),
        'contributes[0].values.relayhost',
    ),
    (
        'value not text',
        manifest(contributes=[{'capability': 'mail.journal', 'values': {'archive_address': 5}}]),
        'contributes[0].values.archive_address',
    ),
    (
        'undeclared placeholder',
        manifest(
            contributes=[{'capability': 'mail.journal', 'values': {'archive_address': '{nope}'}}]
        ),
        'contributes[0].values.archive_address',
    ),
    (
        'unmatched brace',
        manifest(
            contributes=[
                {'capability': 'mail.journal', 'values': {'archive_address': '{archive_address'}}
            ]
        ),
        'contributes[0].values.archive_address',
    ),
    (
        'bad placeholder',
        manifest(
            contributes=[{'capability': 'mail.journal', 'values': {'archive_address': '{Archive}'}}]
        ),
        'contributes[0].values.archive_address',
    ),
    (
        'literal value invalid',
        manifest(
            contributes=[{'capability': 'mail.journal', 'values': {'archive_address': 'two words'}}]
        ),
        'contributes[0].values.archive_address',
    ),
    (
        'literal list injection',
        manifest(
            contributes=[
                {'capability': 'mail.journal', 'values': {'archive_address': 'a@b.test,c@d.test'}}
            ]
        ),
        'contributes[0].values.archive_address',
    ),
    (
        'same key twice',
        manifest(
            contributes=[
                {'capability': 'mail.journal', 'values': {'archive_address': '{archive_address}'}}
            ]
            * 2
        ),
        'contributes[1].values.archive_address',
    ),
]


class ManifestValidationTests(SimpleTestCase):
    def test_the_base_manifest_is_valid(self) -> None:
        m = manifests.load(text())
        self.assertEqual((m.id, m.version, m.category), ('test-journal', '1.0.0', 'compliance'))
        self.assertEqual(m.paragraphs, ['First paragraph.', 'Second paragraph.'])
        self.assertEqual(m.claimed_keys(), {('mail.journal', 'archive_address')})
        self.assertEqual(len(m.sha256), 64)

    def test_each_invalid_manifest_is_rejected_at_the_right_place(self) -> None:
        for name, data, location in INVALID:
            with self.subTest(name):
                with self.assertRaises(ManifestError) as caught:
                    manifests.load(to_toml(data))
                locations = [p[0] for p in caught.exception.problems]
                self.assertIn(location, locations, caught.exception.problems)

    def test_every_problem_is_reported_at_once(self) -> None:
        data = manifest(plugin__id='X', plugin__version='1', plugin__category='fun')
        with self.assertRaises(ManifestError) as caught:
            manifests.load(to_toml(data))
        locations = {p[0] for p in caught.exception.problems}
        self.assertTrue({'plugin.id', 'plugin.version', 'plugin.category'} <= locations)
        self.assertIn('and 2 more', str(caught.exception))

    def test_not_toml_not_utf8_too_big_and_bom(self) -> None:
        with self.assertRaisesMessage(ManifestError, 'not valid TOML'):
            manifests.load('[plugin\nid = ')
        with self.assertRaisesMessage(ManifestError, 'not UTF-8'):
            manifests.load(b'\xff\xfe\x00')
        with self.assertRaisesMessage(ManifestError, 'larger than'):
            manifests.load(b'#' * (MAX_MANIFEST_BYTES + 1))
        with self.assertRaisesMessage(ManifestError, 'larger than'):
            manifests.load('#' * (MAX_MANIFEST_BYTES + 1))
        self.assertEqual(manifests.load('﻿' + text()).id, 'test-journal')
        with self.assertRaisesMessage(ManifestError, 'not valid TOML'):
            manifests.load(text() + '\n[plugin]\nid = "dup"\n')  # duplicate table

    def test_optional_fields_and_valid_variants(self) -> None:
        data = manifest(
            plugin__description=None,
            plugin__requires_core='0.0.1',
            settings=[
                S,
                setting(key='size', type='integer', min=0, max=10, default=3, required=False),
                setting(key='mode', type='choice', options=['a', 'b'], default='b', required=False),
                setting(key='note', type='text', max_length=20, default='hi', required=False),
                setting(key='on', type='boolean', default=True, required=False),
                setting(key='cc', type='email', default='Cc@Example.Test', required=False),
            ],
        )
        m = manifests.load(to_toml(data))
        self.assertEqual(m.setting('size').default, 3)
        self.assertEqual(m.setting('cc').default, 'cc@example.test')
        self.assertEqual(m.setting('archive_address').base_type, 'email')
        self.assertEqual(m.description, '')

    def test_literal_braces_and_parsing_is_cached(self) -> None:
        self.assertEqual(manifests.placeholders('{{x}} {archive_address}'), ['archive_address'])
        self.assertEqual(manifests.expand('{{x}} {a}', {'a': 'v'}), '{x} v')
        self.assertEqual(manifests.expand('{a}', {'a': True}), 'yes')
        self.assertEqual(manifests.expand('{a}', {}), '')
        source = text()
        self.assertIs(manifests.load(source), manifests.load(source))


class SettingsValidationTests(SimpleTestCase):
    def setUp(self) -> None:
        self.m = manifests.load(
            to_toml(
                manifest(
                    settings=[
                        setting(key='n', type='integer', min=1, max=5, required=True),
                        setting(key='mode', type='choice', options=['a', 'b'], required=False),
                        setting(key='t', type='text', max_length=5, required=False, default='d'),
                        setting(key='on', type='boolean', required=False),
                        setting(key='e', type='email', required=False),
                    ],
                    contributes=[
                        {'capability': 'mail.journal', 'values': {'archive_address': '{e}'}}
                    ],
                )
            )
        )

    def clean(self, **values: object) -> dict:
        return manifests.clean_settings(self.m, values)

    def test_good_values_are_normalised(self) -> None:
        cleaned = self.clean(n=' 3 ', mode='b', on='on', e=' A@Example.TEST ', csrf='x')
        self.assertEqual(
            cleaned, {'n': 3, 'mode': 'b', 't': 'd', 'on': True, 'e': 'a@example.test'}
        )

    def test_bad_values_are_all_reported(self) -> None:
        cases = {
            'n': ['', 'x', '0', '6', True, '1.5'],
            'mode': ['c'],
            't': ['toolong', 'a\nb'],
            'e': ['nope', 'a b@c.test', 'a@b.test,c@d.test', 'a@b', '"a"@b.test', 'a@-b.test'],
        }
        for key, bad_values in cases.items():
            for bad in bad_values:
                with self.subTest(key=key, value=bad):
                    values = {'n': '2', key: bad}
                    with self.assertRaises(SettingsError) as caught:
                        manifests.clean_settings(self.m, values)
                    self.assertIn(key, caught.exception.errors)

    def test_boolean_defaults_apply_only_when_not_supplied(self) -> None:
        m = manifests.load(
            to_toml(
                manifest(
                    settings=[S, setting(key='on', type='boolean', default=True, required=False)]
                )
            )
        )
        supplied = {'archive_address': 'a@b.test'}
        self.assertTrue(manifests.clean_settings(m, supplied, live=False)['on'])
        self.assertFalse(manifests.clean_settings(m, {**supplied, 'on': ''}, live=False)['on'])

    def test_a_cleared_field_stays_empty_instead_of_returning_to_the_default(self) -> None:
        m = manifests.load(
            to_toml(
                manifest(settings=[S, setting(key='t', type='text', default='d', required=False)])
            )
        )
        supplied = {'archive_address': 'a@b.test'}
        self.assertEqual(manifests.clean_settings(m, supplied, live=False)['t'], 'd')
        self.assertIsNone(manifests.clean_settings(m, {**supplied, 't': ''}, live=False)['t'])

    def test_missing_optional_values_and_unchecked_boxes(self) -> None:
        cleaned = self.clean(n=1)
        self.assertEqual(cleaned['on'], False)
        self.assertIsNone(cleaned['mode'])
        self.assertIsNone(cleaned['e'])

    def test_rendered_values_are_checked_by_the_point(self) -> None:
        self.assertEqual(
            manifests.rendered_values(self.m, {'e': 'x@y.test'}),
            {'mail.journal': {'archive_address': 'x@y.test'}},
        )
        # Empty clears the key; a value that would smuggle a newline is refused.
        self.assertEqual(
            manifests.rendered_values(self.m, {'e': None})['mail.journal']['archive_address'], ''
        )
        with self.assertRaises(SettingsError):
            manifests.rendered_values(self.m, {'e': 'x@y.test\nrelayhost = evil'})


class BundledCatalogTests(SimpleTestCase):
    def test_bundled_plugins_load_and_their_folder_matches_their_id(self) -> None:
        self.assertEqual(CatalogService.bundled_errors(), ())
        ids = [e.plugin_id for e in CatalogService.bundled()]
        self.assertIn('compliance-journal', ids)
        journal = next(e for e in CatalogService.bundled() if e.plugin_id == 'compliance-journal')
        self.assertEqual(journal.manifest.claimed_keys(), {('mail.journal', 'archive_address')})
        self.assertEqual(journal.manifest.setting('archive_address').type, 'mailbox')
