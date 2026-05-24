import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.config.settings.production')
django.setup()
from django.test import Client
c = Client()

HOST = {'SERVER_NAME': 'ifinsta.online', 'SERVER_PORT': '443'}

print('ROUTE TEST RESULTS')
print('==================')
print()

unauthed = [
    ('/health/',            [200], 'Health check endpoint'),
    ('/admin/',             [302], 'Admin redirect to dashboard'),
    ('/admin/dashboard/',   [302], 'Dashboard (unauthed redirects to login)'),
    ('/django-admin/',      [302], 'Django admin (unauthed redirects to login)'),
    ('/django-admin/login/',[200], 'Admin login page'),
    ('/mail/',              [302], 'Mail inbox (unauthed redirects to login)'),
    ('/nonexistent/',       [404], 'Custom 404 JSON handler'),
]

all_ok = True
for path, expected, desc in unauthed:
    resp = c.get(path, secure=True, **HOST)
    s = resp.status_code
    ok = 'PASS' if s in expected else 'FAIL'
    if ok == 'FAIL':
        all_ok = False
    loc = ''
    if s in (301,302) and resp.get('Location'):
        loc = ' -> ' + resp['Location']
    print('  [%s] GET %-30s %s%s' % (ok, path, s, loc))

print()
if all_ok:
    print('  [PASS] All unauthenticated routes responded correctly')
else:
    print('  [FAIL] Some routes had unexpected status codes')

print()
print('AUTHENTICATED FLOW')
print('------------------')
username = os.environ.get('DJANGO_SUPERUSER_USERNAME', 'admin')
password = os.environ.get('DJANGO_SUPERUSER_PASSWORD', '')
import re

login_page = c.get('/django-admin/login/', secure=True, **HOST)
m = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', login_page.content.decode())
csrf = m.group(1) if m else ''

resp = c.post('/django-admin/login/', {
    'username': username, 'password': password,
    'csrfmiddlewaretoken': csrf, 'next': '/django-admin/',
}, secure=True, **HOST)
login_ok = 'OK' if resp.status_code == 302 else 'FAIL(%d)' % resp.status_code
print('  Login: %s' % login_ok)

if resp.status_code == 302:
    authed = [
        '/admin/dashboard/',
        '/django-admin/',
        '/mail/',
        '/django-admin/auth/user/',
        '/django-admin/auth/group/',
        '/django-admin/auth/user/add/',
    ]
    for path in authed:
        resp = c.get(path, secure=True, **HOST)
        s = resp.status_code
        ok = 'OK' if s == 200 else 'FAIL(%d)' % s
        print('  [%s] GET %s' % (ok, path))

    c.get('/django-admin/logout/', secure=True, **HOST)
    resp = c.get('/django-admin/', secure=True, **HOST)
    s = resp.status_code
    ok = 'OK' if s == 302 else 'FAIL(%d)' % s
    print('  [%s] Logout: /django-admin/ -> %s (expect 302)' % (ok, s))
else:
    print('  Skipping authenticated tests - login failed')

print()
print('ALL TESTS COMPLETE')
