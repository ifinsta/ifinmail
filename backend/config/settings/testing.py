# ruff: noqa: F403,F405
"""Testing settings — in-memory SQLite, no Redis, no real external deps."""

import os

os.environ.setdefault('DJANGO_SECRET_KEY', 'test-key-not-used-in-production')
os.environ.setdefault('DB_NAME', 'test_ifinmail')
os.environ.setdefault('DB_USER', 'test_ifinmail')
os.environ.setdefault('DB_PASSWORD', 'test_ifinmail')

from .base import *

DEBUG = False
SECRET_KEY = 'test-key-not-used-in-production'
ALLOWED_HOSTS = ['*']

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
    }
}

CELERY_BROKER_URL = 'memory://'
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

AXES_ENABLED = False

PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]

LOGGING = {
    'version': 1,
    'disable_existing_loggers': True,
}

# Most tests open pages on a database that never ran the setup wizard; the redirect to the
# wizard has its own tests (accounts/tests/test_setup_required.py), which switch it back on.
SETUP_REQUIRED_REDIRECT = False
