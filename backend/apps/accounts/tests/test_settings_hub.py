"""Tests for the Settings hub: catalogue integrity, access control and read-only config."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from django.http import Http404
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import resolve, reverse

from ..services.effective_config import EffectiveConfig
from ..services.settings_catalogue import PAGE_SLUGS, SettingsCatalogue
from ..views.settings_hub import _BUILDERS, _TEMPLATES, settings_hub, settings_page


def _staff_request(path: str) -> MagicMock:
    request = RequestFactory().get(path)
    user = MagicMock(
        is_authenticated=True,
        is_anonymous=False,
        is_active=True,
        is_staff=True,
        is_superuser=True,
        email='admin@example.com',
    )
    user.get_full_name.return_value = 'Admin Root'
    request.user = user
    request.session = {}
    return request


class CatalogueTests(SimpleTestCase):
    def test_keys_are_unique(self) -> None:
        keys = [i.key for i in SettingsCatalogue.items()]
        assert len(keys) == len(set(keys))

    def test_every_item_resolves_to_a_url(self) -> None:
        for item in SettingsCatalogue.items():
            assert resolve(SettingsCatalogue.url_for(item)), item.key

    def test_every_generic_page_has_content(self) -> None:
        """A catalogue slug without a builder or template would render an empty page."""
        for slug in PAGE_SLUGS:
            assert slug in _BUILDERS or slug in _TEMPLATES, slug

    def test_existing_pages_use_their_active_section_key(self) -> None:
        for key, url_name in {
            'general': 'accounts:branding_identity',
            'spam': 'accounts:spam_filtering',
            'users': 'accounts:user_management',
            'logs': 'accounts:logs',
            'dns': 'dns:config',
        }.items():
            item = SettingsCatalogue.get(key)
            assert item is not None and item.url_name == url_name

    def test_search_keywords_are_lowercase(self) -> None:
        for item in SettingsCatalogue.items():
            assert all(k == k.lower() for k in item.keywords), item.key


class ViewTests(SimpleTestCase):
    def test_hub_renders_every_group_and_item(self) -> None:
        response = settings_hub(_staff_request(reverse('accounts:settings')))
        html = response.content.decode()
        assert response.status_code == 200
        for item in SettingsCatalogue.items():
            assert SettingsCatalogue.url_for(item) in html, item.key
        assert 'ifinmail-settings--hub' in html

    def test_every_generic_page_renders_with_active_nav(self) -> None:
        for slug in sorted(PAGE_SLUGS):
            path = reverse('accounts:settings_page', kwargs={'slug': slug})
            response = settings_page(_staff_request(path), slug)
            html = response.content.decode()
            assert response.status_code == 200, slug
            assert 'aria-current="page"' in html, slug

    def test_unknown_slug_is_404(self) -> None:
        with pytest.raises(Http404):
            settings_page(_staff_request('/accounts/settings/nope/'), 'nope')

    def test_anonymous_users_are_redirected_to_login(self) -> None:
        request = RequestFactory().get(reverse('accounts:settings'))
        request.user = MagicMock(is_authenticated=False)
        response = settings_hub(request)
        assert response.status_code == 302
        assert '/accounts/login/' in response['Location']

    def test_non_staff_users_are_redirected(self) -> None:
        request = _staff_request(reverse('accounts:settings'))
        request.user.is_staff = False
        request.user.is_superuser = False
        response = settings_hub(request)
        assert response.status_code == 302


class EffectiveConfigTests(SimpleTestCase):
    @staticmethod
    def _values(sections: list) -> str:
        return ' '.join(f'{r.label} {r.value}' for s in sections for r in s.rows)

    def test_secrets_are_never_exposed(self) -> None:
        env = {
            'EMAIL_HOST_PASSWORD': 'hunter2-secret',
            'SENTRY_DSN': 'https://key@sentry.example/1',
        }
        with patch.dict('os.environ', env), override_settings(EMAIL_HOST_PASSWORD='hunter2-secret'):
            text = self._values(EffectiveConfig.mail() + EffectiveConfig.monitoring())
        assert 'hunter2-secret' not in text
        assert 'sentry.example' not in text
        assert 'Configured' in text

    def test_unset_secret_is_reported_as_not_set(self) -> None:
        with patch.dict('os.environ', {'SENTRY_DSN': ''}):
            assert 'Not set' in self._values(EffectiveConfig.monitoring())

    def test_all_builders_return_rows(self) -> None:
        for slug, builder in _BUILDERS.items():
            sections = builder()
            assert sections and all(s.rows for s in sections), slug
