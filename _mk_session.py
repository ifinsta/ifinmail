"""Create a dev session for admin@test.com so the live /dns/ page can be reviewed."""

import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.config.settings.development')
django.setup()

from django.contrib.sessions.backends.cached_db import SessionStore  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.utils import timezone  # noqa: E402

User = get_user_model()
user = User.objects.filter(is_superuser=True).order_by('email').first()
if user is None:
    raise SystemExit('no superuser found')
print('user:', user.email, 'pk:', user.pk)

session = SessionStore()
session['_auth_user_id'] = str(user.pk)
session['_auth_user_backend'] = 'django.contrib.auth.backends.ModelBackend'
session['_auth_user_hash'] = user.get_session_auth_hash()
session['mfa_verified_at'] = timezone.now().isoformat()
session.save()
print('sessionid:', session.session_key)
