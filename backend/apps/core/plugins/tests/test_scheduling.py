"""Every beat entry must name a task the worker actually registers (autodiscovery is explicit)."""

from __future__ import annotations

from django.conf import settings
from django.test import SimpleTestCase


class BeatScheduleTests(SimpleTestCase):
    def test_every_scheduled_task_is_registered(self) -> None:
        from backend.config.celery import app

        app.loader.import_default_modules()
        registered = set(app.tasks)
        missing = {
            name: entry['task']
            for name, entry in settings.CELERY_BEAT_SCHEDULE.items()
            if entry['task'] not in registered
        }
        self.assertEqual(missing, {}, 'beat entries whose task the worker would not know')

    def test_plugin_reconcile_runs_often_and_cheaply(self) -> None:
        entry = settings.CELERY_BEAT_SCHEDULE['plugins-reconcile']
        self.assertEqual(entry['task'], 'plugins.reconcile')
