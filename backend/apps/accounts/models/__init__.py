import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.db import models


class MailUserManager(BaseUserManager['MailUser']):
    def create_user(
        self,
        email: str,
        password: str | None = None,
        **extra_fields: object,
    ) -> 'MailUser':
        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        if user.id is None:
            user.id = uuid.uuid4()
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(
        self,
        email: str,
        password: str | None = None,
        **extra_fields: object,
    ) -> 'MailUser':
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        return self.create_user(email, password, **extra_fields)


class MailUser(AbstractBaseUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.CharField(max_length=255, unique=True)
    full_name = models.CharField(max_length=128, blank=True, default='')
    password_hash = models.CharField(max_length=512, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)
    # Console staff must hold a verified second factor unless they turn it off
    # themselves (proving possession first). Re-enrolling sets it back to True.
    mfa_required = models.BooleanField(default=True)
    # Set on the administrator the installer creates: its password was printed in a terminal
    # and sits in provisioning/.env, so the console asks for a new one before anything else.
    password_change_required = models.BooleanField(default=False)
    # Two-factor is offered, not forced: "Remind me in a week" postpones the prompt until then.
    mfa_remind_after = models.DateTimeField(null=True, blank=True)
    role = models.ForeignKey(
        'accounts.Role', null=True, blank=True, on_delete=models.SET_NULL, related_name='users'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = MailUserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        managed = False
        db_table = 'users'

    def __str__(self) -> str:
        return self.email

    def get_full_name(self) -> str:
        """The profile display name; empty when the user has not set one."""
        return self.full_name

    def set_password(self, raw_password: str | None) -> None:
        """Store both Django and Dovecot-compatible password hashes."""
        super().set_password(raw_password)
        self.password_hash = _make_dovecot_password_hash(raw_password)

    def has_perm(self, perm: str, obj: object = None) -> bool:
        return self.is_superuser

    def has_module_perms(self, app_label: str) -> bool:
        return self.is_superuser


class TOTPDevice(models.Model):
    """A verified authenticator-app second factor. Secrets are Fernet-encrypted."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(MailUser, on_delete=models.CASCADE, related_name='totp_devices')
    name = models.CharField(max_length=64, default='Authenticator app')
    secret_encrypted = models.TextField()
    verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'accounts_totp_device'

    def __str__(self) -> str:
        state = 'verified' if self.verified else 'pending'
        return f'TOTP for {self.user_id} ({state})'


class MFARecoveryCode(models.Model):
    """Single-use recovery codes (only hashes stored) for MFA bypass."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(MailUser, on_delete=models.CASCADE, related_name='mfa_recovery_codes')
    code_hash = models.CharField(max_length=128)
    used = models.BooleanField(default=False)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'accounts_mfa_recovery_code'

    def __str__(self) -> str:
        state = 'used' if self.used else 'active'
        return f'Recovery code for {self.user_id} ({state})'


def _make_dovecot_password_hash(raw_password: str | None) -> str:
    """Return a Dovecot ``SHA512-CRYPT`` hash (``$6$...``) for the given password.

    Uses passlib's implementation because the stdlib ``crypt`` module was removed
    in Python 3.13. An empty password yields an empty (unusable) hash so Dovecot
    rejects the login instead of accepting a blank credential.
    """
    if not raw_password:
        return ''
    try:
        from passlib.hash import sha512_crypt
    except ImportError as exc:
        raise RuntimeError(
            'Password hashing needs the "passlib" package '
            '(requirements/base.txt), which is not installed in the Python '
            'running this server. Install project dependencies '
            '(pip install -r requirements/base.txt) or run the server from '
            'the project virtualenv.'
        ) from exc

    return sha512_crypt.using(rounds=5000).hash(raw_password)


class Role(models.Model):
    """A named set of permission codes. System roles are seeded, never edited."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=64)
    description = models.TextField(blank=True, default='')
    permissions = models.JSONField(default=list)
    is_system = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'accounts_role'

    def __str__(self) -> str:
        return f'{self.name} ({self.key})'


class APIToken(models.Model):
    """A scoped first-party token. Only the SHA-256 hash is stored."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(MailUser, on_delete=models.CASCADE, related_name='api_tokens')
    name = models.CharField(max_length=64)
    prefix = models.CharField(max_length=16, unique=True)
    token_hash = models.CharField(max_length=64)
    scopes = models.JSONField(default=list)
    expires_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    last_used_ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # Rotation with overlap: the replaced secret keeps working until this moment, so an
    # integration can switch over without an outage.
    previous_hash = models.CharField(max_length=64, blank=True, default='')
    previous_expires_at = models.DateTimeField(null=True, blank=True)
    # CIDR ranges the key may be used from; empty means anywhere.
    allowed_networks = models.JSONField(default=list, blank=True)
    # Calls per minute; null uses the server default (API_RATE_LIMIT_PER_MINUTE).
    rate_limit_per_minute = models.PositiveIntegerField(null=True, blank=True)
    # Addresses (or ``*@domain``) the key may send as; required for the ``mail.send`` scope.
    allowed_senders = models.JSONField(default=list, blank=True)
    # Recipients per day for ``POST /messages``; null uses API_SEND_LIMIT_PER_DAY.
    send_limit_per_day = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = 'accounts_api_token'

    def __str__(self) -> str:
        return f'{self.name} ({self.prefix}…)'
