"""telemetry — urls.py: nothing is served here any more.

The error log is part of the versioned API (``/api/v1/telemetry/...``, see ``api.py``). The old
unversioned ``/telemetry/<name>/`` paths are redirected by ``backend/config/api_versions.py``.
"""

from django.urls import URLPattern

app_name = 'telemetry'
urlpatterns: list[URLPattern] = []
