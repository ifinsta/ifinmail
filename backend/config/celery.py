"""Celery application: runs the periodic verification, certificate and runtime jobs."""

from __future__ import annotations

import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.config.settings.development')

app = Celery('ifinmail')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks(
    [
        'backend.apps.core',
        'backend.apps.core.plugins',
        'backend.apps.core.storage',
        'backend.apps.core.assistant',
        'backend.apps.core.telemetry',
        'backend.apps.dns',
        'backend.apps.domains',
        'backend.apps.mail',
    ]
)
