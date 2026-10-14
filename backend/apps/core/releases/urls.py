"""releases — urls.py: public machine routes and the console page.

Mounted at the site root, *before* ``accounts/``: the console page sits under
``accounts/settings/`` and must win over the settings hub's ``<slug>`` catch-all.
The human download page (``/download/``) is registered with the other public pages in
``backend/config/public_pages.py``; the JSON manifest is listed in
``backend/config/api_versions.py`` as infrastructure, with its reason.
"""

from django.urls import URLPattern, path

from backend.apps.core.releases import views, web

app_name = 'releases'

urlpatterns: list[URLPattern] = [
    # devices and visitors (no sign-in)
    path('updates/v1/android/latest.json', web.manifest, name='android-manifest'),
    path('download/android/latest.apk', web.latest_apk, name='android-latest'),
    # administrators (Settings → App releases)
    path('accounts/settings/releases/', views.releases_page, name='console'),
    path('accounts/settings/releases/publish/', views.release_publish, name='console_publish'),
    path('accounts/settings/releases/action/', views.release_action, name='console_action'),
]
