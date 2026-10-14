"""Every task the scheduler or the code sends must be registered in the worker.

Celery only imports the ``tasks`` module of the packages listed in ``backend/config/celery.py``.
A task defined in an unlisted app works under test (eager mode imports it directly) and then
fails in production with "Received unregistered task". This test imports what the worker would
import and checks the schedule and every ``.delay`` target against it.
"""

from __future__ import annotations

from django.conf import settings
from django.test import SimpleTestCase


class WorkerRegistrationTests(SimpleTestCase):
    def registered(self) -> set[str]:
        from backend.config.celery import app

        app.loader.import_default_modules()
        return set(app.tasks)

    def test_every_scheduled_task_is_registered(self) -> None:
        registered = self.registered()
        missing = {
            entry['task']
            for entry in settings.CELERY_BEAT_SCHEDULE.values()
            if entry['task'] not in registered
        }
        self.assertEqual(missing, set(), 'scheduled but not registered in the worker')

    def test_the_contact_directory_task_is_registered(self) -> None:
        self.assertIn('accounts.publish_directory', self.registered())
