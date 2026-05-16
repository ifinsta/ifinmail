# Week 8: Django API Development — The ifinmail Platform Layer

**Month 2: Core Mail Stack | Days 43–48**

The API layer is what makes ifinmail a platform, not just a mail server. This week builds the full REST API contract described in proposal Section 7: authentication, mail operations, admin endpoints, device bootstrap, structured errors, and OpenAPI documentation. By Friday, you will have a working Django API that powers both the web client and future official apps.

---

## Learning Goals for the Week

By Sunday, you will be able to:

- Set up a Django project with environment-specific settings (base, development, production, testing)
- Design and implement a versioned REST API using Django Ninja
- Implement Django's built-in auth extended with JWT for API clients
- Build all four API groups: Auth, Mail, Admin, and Device Bootstrap
- Use Django Admin for internal management (domains, users, abuse review)
- Generate OpenAPI documentation automatically
- Write integration tests for the API
- Understand idempotency keys, pagination, and structured errors

---

## Day 1 (Monday): Django Project Setup & Auth Endpoints

### Learning Objectives
- Create a Django project following the ifinsta ecosystem structure
- Configure environment-specific settings (base, development, testing)
- Set up Django's built-in User model with Argon2id password hashing
- Implement login with JWT access/refresh tokens via Django Ninja

### Theory / Reading
- **Django project structure**: `config/` for settings, `apps/` for Django apps (ifinsta pattern)
- **Argon2id**: Django's default password hasher since 4.0+; memory-hard, GPU/ASIC resistant
- **Django Ninja**: typed API framework for Django; auto-generates OpenAPI schema; lighter than DRF
- **JWT for APIs**: Django sessions for web, JWT tokens for API clients (Android, desktop)

### Practical Exercise
```bash
# Create the ifinmail Django project
cd ~
mkdir -p ifinmail && cd ifinmail
python3 -m venv venv
source venv/bin/activate
pip install django django-ninja psycopg2-binary redis django-redis \
            celery pyotp qrcode pyjwt argon2-cffi python-dotenv \
            ruff mypy django-stubs pytest pytest-django

# Start the Django project
django-admin startproject config .
mkdir -p backend/apps
mv config backend/
touch backend/__init__.py
touch backend/apps/__init__.py
```

```
ifinmail/
├── manage.py
├── backend/
│   ├── __init__.py
│   ├── config/              # Django project config (was "config" from startproject)
│   │   ├── __init__.py
│   │   ├── settings/
│   │   │   ├── __init__.py
│   │   │   ├── base.py      # Shared settings
│   │   │   ├── development.py
│   │   │   └── testing.py
│   │   ├── urls.py
│   │   ├── wsgi.py
│   │   └── asgi.py
│   └── apps/
│       ├── __init__.py
│       └── accounts/        # User auth, MFA, sessions
├── requirements/
│   └── base.txt
└── .env.example
```

```python
# backend/config/settings/__init__.py
"""Settings package — DJANGO_SETTINGS_MODULE points here."""
import os
from dotenv import load_dotenv

load_dotenv()

env = os.getenv("DJANGO_ENV", "development")
if env == "testing":
    from .testing import *
elif env == "production":
    from .production import *
else:
    from .development import *
```

```python
# backend/config/settings/base.py
"""Shared settings for all environments."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent

SECRET_KEY = os.getenv("SECRET_KEY", "CHANGE_ME")
DEBUG = False
ALLOWED_HOSTS = []

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "ninja",
    # ifinmail apps
    "backend.apps.accounts",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "backend.config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "backend.config.wsgi.application"

# Password hashing — Argon2id (proposal Section 13.1)
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
```

```python
# backend/config/settings/development.py
"""Development settings."""
from .base import *

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME", "ifinmail_dev"),
        "USER": os.getenv("DB_USER", "ifinmail"),
        "PASSWORD": os.getenv("DB_PASSWORD", "ifinmail"),
        "HOST": os.getenv("DB_HOST", "localhost"),
        "PORT": os.getenv("DB_PORT", "5432"),
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    }
}

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
```

```python
# backend/config/settings/testing.py
"""Testing settings."""
from .base import *

DEBUG = True
SECRET_KEY = "testing-secret-key-not-for-production"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",  # Fast for tests
]
```

```python
# backend/apps/accounts/models.py
"""Account models — extends Django User with MFA and device tracking."""
from django.db import models
from django.conf import settings
import pyotp

class MFAProfile(models.Model):
    """MFA TOTP profile for a user (proposal Section 7.2 Auth API)."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mfa_profile")
    totp_secret = models.CharField(max_length=32, blank=True)
    is_enabled = models.BooleanField(default=False)
    backup_codes = models.JSONField(default=list, blank=True)

    def generate_totp_secret(self):
        self.totp_secret = pyotp.random_base32()
        self.save()
        return self.totp_secret

    def get_totp_uri(self):
        return pyotp.totp.TOTP(self.totp_secret).provisioning_uri(
            name=self.user.email, issuer_name="ifinmail"
        )

    def verify_code(self, code: str) -> bool:
        return pyotp.TOTP(self.totp_secret).verify(code)

    def generate_backup_codes(self, count=8):
        import secrets
        self.backup_codes = [secrets.token_hex(4) for _ in range(count)]
        self.save()
        return self.backup_codes


class Session(models.Model):
    """Track active sessions for session listing and revocation."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sessions")
    device_name = models.CharField(max_length=255)
    ip_address = models.GenericIPAddressField()
    created_at = models.DateTimeField(auto_now_add=True)
    last_active = models.DateTimeField(auto_now=True)
    is_revoked = models.BooleanField(default=False)

    class Meta:
        ordering = ["-last_active"]
```

```python
# backend/apps/accounts/api.py
"""Auth API endpoints using Django Ninja (proposal Section 7.2)."""
from ninja import Router, Schema
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from ninja.security import HttpBearer
from typing import Optional
from datetime import datetime, timedelta
import jwt
import hashlib

router = Router(tags=["Auth"])

JWT_SECRET = "CHANGE_ME_IN_PRODUCTION"
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 30


# --- Schemas ---
class LoginRequest(Schema):
    email: str
    password: str
    device_name: Optional[str] = "Unknown"


class LoginResponse(Schema):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 1800


class TokenRefreshRequest(Schema):
    refresh_token: str


class MfaSetupResponse(Schema):
    secret: str
    qr_code_url: str
    backup_codes: list[str]


class SessionInfo(Schema):
    session_id: int
    device_name: str
    ip_address: str
    created_at: datetime
    last_active: datetime


# --- Auth helpers ---
def create_access_token(user_id: int, email: str) -> str:
    now = datetime.utcnow()
    payload = {
        "sub": str(user_id),
        "email": email,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        "jti": hashlib.sha256(f"{user_id}{now.timestamp()}".encode()).hexdigest()[:16],
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: int, session_id: int) -> str:
    now = datetime.utcnow()
    payload = {
        "sub": str(user_id),
        "session_id": session_id,
        "type": "refresh",
        "iat": now,
        "exp": now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        "jti": hashlib.sha256(f"{session_id}{now.timestamp()}".encode()).hexdigest()[:16],
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


class AuthBearer(HttpBearer):
    def authenticate(self, request, token):
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            if payload.get("type") != "access":
                return None
            user = User.objects.get(id=payload["sub"])
            return user
        except (jwt.InvalidTokenError, User.DoesNotExist):
            return None


auth = AuthBearer()


# --- Endpoints ---
@router.post("/login", response=LoginResponse)
def login(request, data: LoginRequest):
    """Authenticate user and return JWT tokens."""
    user = authenticate(username=data.email, password=data.password)
    if not user:
        return {"detail": "Invalid credentials"}

    session = Session.objects.create(
        user=user,
        device_name=data.device_name,
        ip_address=request.META.get("REMOTE_ADDR", "0.0.0.0"),
    )

    access = create_access_token(user.id, user.email)
    refresh = create_refresh_token(user.id, session.id)

    return LoginResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/refresh", response=LoginResponse)
def refresh_token(request, data: TokenRefreshRequest):
    """Refresh an access token using a valid refresh token."""
    try:
        payload = jwt.decode(data.refresh_token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "refresh":
            return {"detail": "Invalid token type"}

        session = Session.objects.get(id=payload["session_id"], is_revoked=False)
        access = create_access_token(session.user.id, session.user.email)
        return LoginResponse(access_token=access, refresh_token=data.refresh_token)
    except (jwt.InvalidTokenError, Session.DoesNotExist):
        return {"detail": "Invalid or revoked refresh token"}


@router.get("/sessions", response=list[SessionInfo], auth=auth)
def list_sessions(request):
    """List all active sessions for the authenticated user."""
    sessions = Session.objects.filter(user=request.auth, is_revoked=False)
    return [
        SessionInfo(
            session_id=s.id,
            device_name=s.device_name,
            ip_address=s.ip_address,
            created_at=s.created_at,
            last_active=s.last_active,
        )
        for s in sessions
    ]


@router.delete("/sessions/{session_id}", auth=auth)
def revoke_session(request, session_id: int):
    """Revoke a specific session."""
    session = Session.objects.get(id=session_id, user=request.auth)
    session.is_revoked = True
    session.save()
    return {"status": "revoked"}


@router.get("/mfa/setup", response=MfaSetupResponse, auth=auth)
def setup_mfa(request):
    """Generate TOTP secret and QR code URL for MFA setup."""
    profile, _ = MFAProfile.objects.get_or_create(user=request.auth)
    secret = profile.generate_totp_secret()
    codes = profile.generate_backup_codes()
    return MfaSetupResponse(
        secret=secret,
        qr_code_url=profile.get_totp_uri(),
        backup_codes=codes,
    )
```

### Checkpoint Questions
1. Why does Django's built-in auth use Argon2id by default?
2. What is the difference between Django sessions (cookie-based) and JWT tokens (stateless)?
3. Why use Django Ninja instead of Django REST Framework for ifinmail?
4. How would you implement session revocation when using JWTs?

### Connection to ifinmail
Auth is the gateway to every API call. Django's built-in auth gives us user management, password hashing, and admin integration for free. Django Ninja adds clean, typed API endpoints with auto-generated OpenAPI docs.

---

## Day 2 (Tuesday): Mail API Endpoints

### Learning Objectives
- Implement the full Mail API group (proposal Section 7.2)
- Handle pagination, filtering, and sorting with Django Ninja
- Implement idempotency keys for write operations
- Connect API endpoints to Dovecot Maildir or message metadata in PostgreSQL

### Theory / Reading
- **Pagination**: Django's built-in paginator; cursor-based for large mailboxes
- **Idempotency key**: client-generated unique key; server stores key + result to prevent duplicate processing
- **Django Ninja routers**: organize endpoints into logical groups

### Practical Exercise
```python
# backend/apps/mail/models.py
"""Mail metadata models (proposal Section 11)."""
from django.db import models
from django.conf import settings


class Mailbox(models.Model):
    """IMAP mailbox/folder for a user."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mailboxes")
    name = models.CharField(max_length=255)  # INBOX, Sent, Drafts, Archive, etc.
    total_messages = models.PositiveIntegerField(default=0)
    unread_count = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ["user", "name"]

    def __str__(self):
        return f"{self.user.email}::{self.name}"


class MessageMeta(models.Model):
    """Message metadata indexed for search (actual content in Dovecot Maildir)."""
    mailbox = models.ForeignKey(Mailbox, on_delete=models.CASCADE, related_name="messages")
    message_id = models.CharField(max_length=255, unique=True)  # IMAP UID or Message-ID header
    sender = models.CharField(max_length=255)
    sender_email = models.EmailField()
    subject = models.CharField(max_length=1000, default="")
    received_at = models.DateTimeField()
    has_attachments = models.BooleanField(default=False)
    flags = models.JSONField(default=list)  # ["\\Seen", "\\Flagged", etc.]
    is_archived = models.BooleanField(default=False)
    is_trashed = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["mailbox", "received_at"]),
            models.Index(fields=["sender_email"]),
            models.Index(fields=["subject"]),
        ]

    def __str__(self):
        return f"{self.sender} — {self.subject}"


class IdempotencyKey(models.Model):
    """Prevent duplicate processing of client requests (proposal Section 7.1)."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    key = models.CharField(max_length=255, unique=True)
    response_data = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["user", "key"])]
```

```python
# backend/apps/mail/api.py
"""Mail API endpoints using Django Ninja (proposal Section 7.2)."""
from ninja import Router, Schema, Query
from typing import Optional, List
from datetime import datetime
from django.core.paginator import Paginator

from backend.apps.mail.models import Mailbox, MessageMeta, IdempotencyKey
from backend.apps.accounts.api import auth

router = Router(tags=["Mail"])


# --- Schemas ---
class MailboxSummary(Schema):
    name: str
    total: int
    unread: int


class MessageSummary(Schema):
    id: str
    sender: str
    subject: str
    snippet: str = ""
    flags: List[str] = []
    has_attachments: bool = False
    received_at: datetime


class MessageDetail(Schema):
    id: str
    sender: str
    to: List[str]
    cc: List[str] = []
    subject: str
    body_text: str
    body_html: Optional[str] = None
    flags: List[str] = []
    attachments: List[dict] = []
    received_at: datetime


class SendRequest(Schema):
    to: List[str]
    cc: Optional[List[str]] = []
    bcc: Optional[List[str]] = []
    subject: str
    body_text: str
    body_html: Optional[str] = None
    in_reply_to: Optional[str] = None


# --- Endpoints ---
@router.get("/mailboxes", response=List[MailboxSummary], auth=auth)
def list_mailboxes(request):
    """List mailboxes for the authenticated user."""
    mailboxes = Mailbox.objects.filter(user=request.auth)
    return [
        MailboxSummary(name=mb.name, total=mb.total_messages, unread=mb.unread_count)
        for mb in mailboxes
    ]


@router.get("/messages", auth=auth)
def list_messages(
    request,
    mailbox: str = Query("INBOX"),
    limit: int = Query(50, ge=1, le=200),
    page: int = Query(1, ge=1),
    sort: str = Query("-received_at"),
):
    """List messages in a mailbox with pagination."""
    qs = MessageMeta.objects.filter(mailbox__name=mailbox, mailbox__user=request.auth)
    if sort.startswith("-"):
        qs = qs.order_by(f"-{sort[1:]}")
    else:
        qs = qs.order_by(sort)

    paginator = Paginator(qs, limit)
    page_obj = paginator.get_page(page)

    return {
        "mailbox": mailbox,
        "page": page,
        "limit": limit,
        "total": paginator.count,
        "has_more": page_obj.has_next(),
        "messages": [
            MessageSummary(
                id=m.message_id,
                sender=m.sender,
                subject=m.subject,
                flags=m.flags,
                has_attachments=m.has_attachments,
                received_at=m.received_at,
            )
            for m in page_obj
        ],
    }


@router.get("/messages/{message_id}", response=MessageDetail, auth=auth)
def read_message(request, message_id: str):
    """Read a single message by ID."""
    msg = MessageMeta.objects.get(message_id=message_id, mailbox__user=request.auth)
    # In production: fetch body from Dovecot Maildir or attachment store
    return MessageDetail(
        id=msg.message_id,
        sender=msg.sender,
        to=[msg.sender_email],
        subject=msg.subject,
        body_text="(fetch from Maildir in production)",
        flags=msg.flags,
        received_at=msg.received_at,
    )


@router.post("/messages", status_code=202, auth=auth)
def send_message(request, data: SendRequest, idempotency_key: Optional[str] = None):
    """
    Queue a message for delivery.
    Idempotency key prevents duplicate sends (proposal Section 7.1).
    """
    if idempotency_key:
        existing = IdempotencyKey.objects.filter(user=request.auth, key=idempotency_key).first()
        if existing:
            return existing.response_data

    # In production: validate recipients, check trust level, queue to Postfix
    response = {"status": "queued", "message_id": "pending", "accepted": data.to}

    if idempotency_key:
        IdempotencyKey.objects.create(user=request.auth, key=idempotency_key, response_data=response)

    return response


@router.post("/messages/{message_id}/move", auth=auth)
def move_message(request, message_id: str, mailbox: str):
    """Move a message to another mailbox."""
    valid = {"INBOX", "Archive", "Trash", "Junk", "Sent", "Drafts"}
    if mailbox not in valid:
        return 400, {"code": "INVALID_MAILBOX", "message": f"'{mailbox}' is not valid"}

    msg = MessageMeta.objects.get(message_id=message_id, mailbox__user=request.auth)
    if mailbox == "Archive":
        msg.is_archived = True
    elif mailbox == "Trash":
        msg.is_trashed = True
    msg.save()
    return {"status": "ok", "message_id": message_id, "mailbox": mailbox}


@router.post("/messages/{message_id}/flags", auth=auth)
def update_flags(request, message_id: str, add: List[str] = None, remove: List[str] = None):
    """Add or remove IMAP flags."""
    msg = MessageMeta.objects.get(message_id=message_id, mailbox__user=request.auth)
    flags = set(msg.flags)
    for f in (add or []):
        flags.add(f)
    for f in (remove or []):
        flags.discard(f)
    msg.flags = list(flags)
    msg.save()
    return {"status": "ok", "flags_added": add, "flags_removed": remove}


@router.get("/search", auth=auth)
def search_messages(
    request,
    q: str = Query(..., min_length=1),
    mailbox: Optional[str] = None,
    limit: int = Query(50, ge=1, le=100),
):
    """Full-text search across messages (PostgreSQL FTS — proposal Section 12)."""
    qs = MessageMeta.objects.filter(mailbox__user=request.auth)
    if mailbox:
        qs = qs.filter(mailbox__name=mailbox)
    qs = qs.filter(subject__icontains=q) | qs.filter(sender__icontains=q)
    qs = qs[:limit]

    return {
        "query": q,
        "mailbox": mailbox,
        "total": qs.count(),
        "messages": [
            MessageSummary(
                id=m.message_id, sender=m.sender, subject=m.subject, received_at=m.received_at
            )
            for m in qs
        ],
    }
```

### Checkpoint Questions
1. Why return HTTP 202 (Accepted) for send_message instead of 200 or 201?
2. How does an idempotency key prevent duplicate sends?
3. Why is Django's ORM better than raw SQL for this use case?
4. What is the difference between message metadata (PostgreSQL) and message content (Maildir)?

### Connection to ifinmail
This is the exact API contract from proposal Section 7.2. Every official client calls these same endpoints. Django's ORM handles pagination, filtering, and indexing automatically.

---

## Day 3 (Wednesday): Admin API & Django Admin

### Learning Objectives
- Implement the Admin API group for domain and user management
- Configure Django Admin for internal platform management
- Add request validation and structured error responses
- Implement API versioning strategy

### Theory / Reading
- **Django Admin**: built-in admin interface; free CRUD UI for any model
- **Django Ninja APIRouter**: organize endpoints by version and scope
- **Versioning**: URL prefix (`/v1/`) + deprecation headers; backward compatibility

### Practical Exercise
```python
# backend/apps/admin/models.py
"""Admin models — domains, organizations, DNS verification."""
from django.db import models
from django.conf import settings


class Organization(models.Model):
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Domain(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="domains")
    name = models.CharField(max_length=255, unique=True)
    is_verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)

    # DNS records generated for this domain
    dkim_selector = models.CharField(max_length=64, default="default")
    dkim_public_key = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class DnsVerification(models.Model):
    """Track DNS verification checks for a domain."""
    domain = models.ForeignKey(Domain, on_delete=models.CASCADE, related_name="dns_checks")
    check_type = models.CharField(max_length=20)  # mx, spf, dkim, dmarc, mta_sts
    status = models.CharField(max_length=10)  # PASS, WARN, FAIL, PENDING
    message = models.TextField(blank=True)
    checked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-checked_at"]
```

```python
# backend/apps/admin/api.py
"""Admin API endpoints (proposal Section 7.2)."""
from ninja import Router, Schema
from typing import Optional, List
from datetime import datetime

from backend.apps.admin.models import Organization, Domain, DnsVerification
from backend.apps.accounts.api import auth

router = Router(tags=["Admin"])


class OrgCreate(Schema):
    name: str
    slug: str


class DomainCreate(Schema):
    organization_id: int
    name: str


class UserCreate(Schema):
    organization_id: int
    username: str
    email: str
    password: str


class DnsHealthCheck(Schema):
    check: str
    status: str
    message: str


@router.get("/organizations", auth=auth)
def list_organizations(request):
    """List all organizations."""
    orgs = Organization.objects.all()
    return {"organizations": [{"id": o.id, "name": o.name, "slug": o.slug} for o in orgs]}


@router.post("/organizations", status_code=201, auth=auth)
def create_organization(request, data: OrgCreate):
    """Create a new organization."""
    org = Organization.objects.create(name=data.name, slug=data.slug)
    return {"status": "created", "organization": {"id": org.id, "name": org.name}}


@router.get("/domains", auth=auth)
def list_domains(request, organization_id: Optional[int] = None):
    """List domains, optionally filtered by organization."""
    qs = Domain.objects.all()
    if organization_id:
        qs = qs.filter(organization_id=organization_id)
    return {"domains": [{"id": d.id, "name": d.name, "verified": d.is_verified} for d in qs]}


@router.post("/domains", status_code=201, auth=auth)
def add_domain(request, data: DomainCreate):
    """Add a domain to an organization."""
    org = Organization.objects.get(id=data.organization_id)
    domain = Domain.objects.create(organization=org, name=data.name)
    return {"status": "created", "domain": {"id": domain.id, "name": domain.name}}


@router.post("/domains/verify", auth=auth)
def verify_domain(request, domain_id: int):
    """Trigger DNS verification for a domain."""
    domain = Domain.objects.get(id=domain_id)
    # In production: run DNS checks (MX, SPF, DKIM, DMARC)
    return {"domain_id": domain.id, "verification_status": "pending"}


@router.get("/domains/{domain_id}/dns-health", auth=auth)
def domain_dns_health(request, domain_id: int):
    """Get DNS health status (proposal Section 6.5)."""
    checks = DnsVerification.objects.filter(domain_id=domain_id)[:10]
    return {
        "domain_id": domain_id,
        "checks": [
            {"check": c.check_type, "status": c.status, "message": c.message}
            for c in checks
        ],
    }


@router.get("/deliverability", auth=auth)
def deliverability_overview(request):
    """Platform-wide deliverability dashboard (proposal Section 6.5)."""
    return {
        "overview": {"total_domains": 0, "healthy_domains": 0, "warning_domains": 0, "failing_domains": 0},
        "metrics": {"bounce_rate_24h": 0.0, "complaint_rate_24h": 0.0, "delivery_rate_24h": 0.0},
        "warnings": [],
    }
```

```python
# backend/apps/admin/admin.py
"""Django Admin configuration for internal platform management."""
from django.contrib import admin
from .models import Organization, Domain, DnsVerification


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "created_at"]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ["name", "organization", "is_verified", "verified_at"]
    list_filter = ["is_verified", "organization"]
    search_fields = ["name"]
    actions = ["trigger_dns_verification"]

    def trigger_dns_verification(self, request, queryset):
        # In production: enqueue Celery task for DNS verification
        self.message_user(request, f"DNS verification triggered for {queryset.count()} domains")
    trigger_dns_verification.short_description = "Verify DNS for selected domains"


@admin.register(DnsVerification)
class DnsVerificationAdmin(admin.ModelAdmin):
    list_display = ["domain", "check_type", "status", "checked_at"]
    list_filter = ["status", "check_type"]
    readonly_fields = ["checked_at"]
```

```python
# backend/config/urls.py
"""Root URL configuration."""
from django.contrib import admin
from django.urls import path
from ninja import NinjaAPI

from backend.apps.accounts.api import router as auth_router
from backend.apps.mail.api import router as mail_router
from backend.apps.admin.api import router as admin_router

api_v1 = NinjaAPI(title="ifinmail API", version="v1", docs_url="/v1/docs")

api_v1.add_router("/auth", auth_router)
api_v1.add_router("/mail", mail_router)
api_v1.add_router("/admin", admin_router)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("v1/", api_v1.urls),
]
```

### Checkpoint Questions
1. What does Django Admin give you "for free" that you'd have to build from scratch with FastAPI?
2. Why separate the Admin API from the Mail API?
3. How would the DNS health endpoint integrate with a Celery background task?
4. What audit events should Django Admin log automatically?

### Connection to ifinmail
Django Admin is the internal dashboard for managing domains, users, and abuse review. The Admin API is for programmatic access. Both share the same models — no duplication.

---

## Day 4 (Thursday): Device Bootstrap API

### Learning Objectives
- Implement the Device Bootstrap API (proposal Section 8)
- Generate and manage device credentials
- Understand the bootstrap flow: manifest → auth → device registration → sync

### Theory / Reading
- **Device Bootstrap**: standardized onboarding so every client sets up the same way
- **Bootstrap manifest**: server advertises API version, auth methods, feature flags
- **Device credentials**: per-device keys stored in platform key stores

### Practical Exercise
```python
# backend/apps/devices/models.py
"""Device registration and bootstrap models (proposal Section 8)."""
from django.db import models
from django.conf import settings


class Device(models.Model):
    """Registered device for a user."""
    PLATFORMS = [
        ("android", "Android"),
        ("windows", "Windows"),
        ("macos", "macOS"),
        ("linux", "Linux"),
        ("web", "Web"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="devices")
    device_id = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    platform = models.CharField(max_length=20, choices=PLATFORMS)
    platform_version = models.CharField(max_length=100, blank=True)
    app_version = models.CharField(max_length=50, blank=True)
    public_key = models.TextField(blank=True)
    push_token = models.CharField(max_length=255, blank=True)
    is_revoked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_seen"]

    def __str__(self):
        return f"{self.name} ({self.platform})"
```

```python
# backend/apps/devices/api.py
"""Device Bootstrap API (proposal Section 8)."""
from ninja import Router, Schema
from typing import Optional, List
from datetime import datetime
import uuid

from backend.apps.devices.models import Device
from backend.apps.accounts.api import auth, create_access_token, create_refresh_token

router = Router(tags=["Devices"])


class BootstrapManifest(Schema):
    service: str = "ifinmail"
    api_version: str = "v1"
    minimum_client_version: str = "1.0.0"
    auth_methods: List[str] = ["password", "mfa_totp", "passkey", "device_approval"]
    endpoints: dict = {
        "api": "https://api.ifinmail.com/v1",
        "websocket": "wss://api.ifinmail.com/v1/events",
        "status": "https://status.ifinmail.com",
    }
    security: dict = {
        "tls_required": True,
        "certificate_pinning": True,
        "device_key_required": True,
        "token_rotation_minutes": 30,
    }
    features: dict = {
        "offline_mail": True,
        "encrypted_cache": True,
        "push_notifications": True,
        "local_search": True,
    }


class DeviceRegisterRequest(Schema):
    device_name: str
    platform: str
    platform_version: str
    app_version: str
    public_key: Optional[str] = None
    push_token: Optional[str] = None


class DeviceCredential(Schema):
    device_id: str
    access_token: str
    refresh_token: str
    sync_settings: dict
    feature_flags: dict


class DeviceInfo(Schema):
    id: str
    name: str
    platform: str
    last_seen: datetime


# --- Bootstrap Endpoints ---
@router.get("/bootstrap/manifest", response=BootstrapManifest)
def get_manifest(request):
    """Return the bootstrap manifest (proposal Section 8.2)."""
    return BootstrapManifest()


@router.post("/register", response=DeviceCredential, auth=auth)
def register_device(request, data: DeviceRegisterRequest):
    """Register a new device after authentication."""
    device_id = f"dev_{uuid.uuid4().hex[:12]}"

    device = Device.objects.create(
        user=request.auth,
        device_id=device_id,
        name=data.device_name,
        platform=data.platform,
        platform_version=data.platform_version,
        app_version=data.app_version,
        public_key=data.public_key or "",
        push_token=data.push_token or "",
    )

    access = create_access_token(request.auth.id, request.auth.email)
    refresh = create_refresh_token(request.auth.id, device.id)

    return DeviceCredential(
        device_id=device_id,
        access_token=access,
        refresh_token=refresh,
        sync_settings={
            "sync_interval_seconds": 300,
            "max_cache_size_mb": 500,
            "sync_mailboxes": ["INBOX", "Sent", "Archive"],
        },
        feature_flags={
            "offline_mail": True,
            "encrypted_cache": True,
            "push_notifications": True,
        },
    )


@router.post("/{device_id}/rotate", auth=auth)
def rotate_credential(request, device_id: str):
    """Rotate a device credential."""
    device = Device.objects.get(device_id=device_id, user=request.auth)
    new_token = create_access_token(request.auth.id, request.auth.email)
    return {"device_id": device_id, "new_token": new_token, "old_token_expires_in": 300}


@router.delete("/{device_id}", auth=auth)
def revoke_device(request, device_id: str):
    """Revoke a device's access."""
    device = Device.objects.get(device_id=device_id, user=request.auth)
    device.is_revoked = True
    device.save()
    return {"status": "revoked", "device_id": device_id}


@router.get("/", response=List[DeviceInfo], auth=auth)
def list_devices(request):
    """List all devices for the authenticated user."""
    devices = Device.objects.filter(user=request.auth, is_revoked=False)
    return [
        DeviceInfo(id=d.device_id, name=d.name, platform=d.platform, last_seen=d.last_seen)
        for d in devices
    ]
```

### Checkpoint Questions
1. Why does the bootstrap manifest exist as a separate endpoint instead of hardcoding client configuration?
2. What is the benefit of device-specific credentials vs sharing the user's main token?
3. How does device revocation work with JWTs?
4. What events should be pushed over WebSocket vs polled via REST?

### Connection to ifinmail
The bootstrap contract ensures every official app (Android, Windows, macOS, Linux, web) starts with the same `/bootstrap/manifest` call. Device-specific credentials mean revoking one device does not affect others.

---

## Day 5 (Friday): Testing, Error Handling & API Polish

### Learning Objectives
- Write integration tests for the API using pytest and pytest-django
- Implement consistent error handling with Django Ninja
- Add rate limiting middleware
- Understand CORS, security headers, and API hardening

### Theory / Reading
- **pytest-django**: Django-aware test runner; handles DB setup/teardown
- **Django Ninja errors**: automatic 422 validation errors; custom handlers for business logic
- **Rate limiting**: Django middleware or Django Ninja decorator with Redis

### Practical Exercise
```python
# pytest.ini
[pytest]
DJANGO_SETTINGS_MODULE = backend.config.settings.testing
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -v --tb=short
```

```python
# conftest.py
"""Shared pytest fixtures."""
import pytest
from django.contrib.auth.models import User


@pytest.fixture
def user(db):
    """Create a test user."""
    return User.objects.create_user(
        username="alice@ifinmail.local",
        email="alice@ifinmail.local",
        password="test_password_123",
    )


@pytest.fixture
def auth_headers(client, user):
    """Create authenticated request headers."""
    from backend.apps.accounts.api import create_access_token
    token = create_access_token(user.id, user.email)
    client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    return client
```

```python
# backend/apps/accounts/tests/test_auth.py
"""Integration tests for the Auth API."""
import pytest
from django.contrib.auth.models import User


@pytest.mark.django_db
def test_health_check(client):
    """Django's built-in check."""
    from django.core.management import call_command
    call_command("check")


@pytest.mark.django_db
def test_login_success(client, user):
    """Login with valid credentials returns tokens."""
    response = client.post(
        "/v1/auth/login",
        data='{"email": "alice@ifinmail.local", "password": "test_password_123"}',
        content_type="application/json",
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.django_db
def test_login_failure(client):
    """Login with wrong password returns error."""
    response = client.post(
        "/v1/auth/login",
        data='{"email": "wrong@ifinmail.local", "password": "wrong"}',
        content_type="application/json",
    )
    assert response.status_code in [401, 422]


@pytest.mark.django_db
def test_bootstrap_manifest(client):
    """Bootstrap manifest returns correct structure."""
    response = client.get("/v1/devices/bootstrap/manifest")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "ifinmail"
    assert data["api_version"] == "v1"
    assert "password" in data["auth_methods"]
    assert data["security"]["tls_required"] is True


@pytest.mark.django_db
def test_list_mailboxes_requires_auth(client):
    """Mail API requires authentication."""
    response = client.get("/v1/mail/mailboxes")
    assert response.status_code in [401, 403]


@pytest.mark.django_db
def test_send_message_validation(auth_headers):
    """Send endpoint validates required fields."""
    response = auth_headers.post("/v1/mail/messages", data="{}", content_type="application/json")
    # Django Ninja returns 422 for validation errors
    assert response.status_code in [202, 422]
```

```bash
# Run the tests
cd ~/ifinmail
source venv/bin/activate
export DJANGO_ENV=testing
python manage.py test
# or with pytest:
pytest -v
```

```python
# backend/config/settings/base.py additions
# Add to MIDDLEWARE for security headers:

class SecurityHeadersMiddleware:
    """Add security headers to every response."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response["X-Content-Type-Options"] = "nosniff"
        response["X-Frame-Options"] = "DENY"
        response["X-Ifinmail-API-Version"] = "v1"
        return response
```

### Checkpoint Questions
1. Why is it important to test the full HTTP stack (integration tests) rather than just unit tests?
2. How does Django Ninja handle validation errors automatically?
3. What security headers should every ifinmail API response include?
4. How would you test rate limiting behavior?

### Connection to ifinmail
Testing is not optional for an email platform. A bug in the send endpoint could mean lost messages. Django's test framework + pytest-django gives you a clean, isolated test database for every test.

---

## Day 6 (Saturday): Review & Integration

### Review Challenge: API Integration Test Suite

Build a comprehensive integration test script that:

1. Tests the full user lifecycle: register → login → refresh token → logout
2. Tests the mail lifecycle: list mailboxes → list messages → read message → send message
3. Tests the device lifecycle: get manifest → register device → rotate credential → revoke
4. Tests admin endpoints: create org → add domain → verify DNS → create user → create mailbox
5. Tests error handling: invalid auth, bad request, not found, rate limited
6. Generates a test report in JSON format

**Stretch goal**: Add performance benchmarks (response time p50/p95/p99 for each endpoint).

### Week 8 Self-Assessment

Before moving to Week 9, confirm you can:
- [ ] Set up a Django project with environment-specific settings
- [ ] Implement Django auth with Argon2id and JWT token generation
- [ ] Build versioned REST APIs using Django Ninja
- [ ] Define Pydantic-compatible Ninja Schemas for request/response validation
- [ ] Generate OpenAPI documentation automatically (`/v1/docs`)
- [ ] Use Django Admin for internal platform management
- [ ] Implement the Device Bootstrap API with manifest
- [ ] Write integration tests using pytest and pytest-django

---

## Week 8 Resource Index

| Resource | Location |
|---|---|
| Django project | `backend/` |
| Settings | `backend/config/settings/` |
| Accounts app | `backend/apps/accounts/` |
| Mail app | `backend/apps/mail/` |
| Admin app | `backend/apps/admin/` |
| Devices app | `backend/apps/devices/` |
| Test suite | `backend/apps/*/tests/` |
| OpenAPI schema | `http://localhost:8000/v1/openapi.json` |
| Swagger docs | `http://localhost:8000/v1/docs` |

---

## Month 2 Completion Checklist

- [ ] **Postfix**: Virtual domains, PostgreSQL maps, TLS, submission, queues
- [ ] **Dovecot**: Maildir, SQL auth, LMTP with Postfix, Sieve, doveadm
- [ ] **Email Security**: SPF, DKIM, DMARC, Rspamd milter, MTA-STS, DNS health
- [ ] **API Platform**: Auth, Mail, Admin, Device Bootstrap API groups with tests

You can now build and operate a complete mail platform. Month 3 adds Rust, the frontend, deployment, and the capstone project.

---

*Week 8 of 12 — Django API Development for ifinmail Platform Engineering*
