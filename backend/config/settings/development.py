# ruff: noqa: E402,F403,F405
# E402: the .env load and dev fallbacks must run before `from .base import *`.
import os
from pathlib import Path

from backend.config.env import load_dotenv

# Local runs read the repo .env (real environment variables win). This happens
# before the fallbacks below so values copied from .env.example take effect.
load_dotenv(Path(__file__).resolve().parents[3] / '.env')

os.environ.setdefault('DJANGO_SECRET_KEY', 'dev-insecure-key-change-in-production')
os.environ.setdefault('DB_NAME', 'ifinmail')
os.environ.setdefault('DB_USER', 'ifinmail')
os.environ.setdefault('DB_PASSWORD', 'ifinmail')

from .base import *

DEBUG = True
ALLOWED_HOSTS = ['localhost', '127.0.0.1', '0.0.0.0']

INSTALLED_APPS += [
    'django_extensions',
]

# Use SQLite for local development when Postgres is unavailable
if os.environ.get('USE_SQLITE') or not os.environ.get('DB_HOST'):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        }
    }

LOGIN_REDIRECT_URL = '/accounts/dashboard/'
LOGIN_URL = '/accounts/login/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

# Content Security Policy
# django-csp ships a bare `default-src 'self'` when no directives are set, which
# blocks the console's own inline theming styles, Google Fonts and data-URI icons.
# Mirror the allowances production.py makes (minus report-only) so local runs match
# what actually ships; scripts stay same-origin-only (no inline scripts/handlers).
CSP_STYLE_SRC = ("'self'", "'unsafe-inline'", 'https://fonts.googleapis.com')
CSP_FONT_SRC = ("'self'", 'https://fonts.gstatic.com')
CSP_IMG_SRC = ("'self'", 'data:', 'blob:')
CSP_CONNECT_SRC = ("'self'",)
CSP_FRAME_ANCESTORS = ("'none'",)
CSP_BASE_URI = ("'self'",)
