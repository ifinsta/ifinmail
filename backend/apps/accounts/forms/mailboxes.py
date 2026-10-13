"""Forms for the Mailboxes and Aliases pages."""

from __future__ import annotations

import re

from django import forms

from backend.apps.mail.types.quota import DEFAULT_QUOTA_BYTES, MB

_MB = MB
_LOCAL_PART_RE = re.compile(r'^[a-z0-9](?:[a-z0-9._+-]{0,62}[a-z0-9])?$')


def clean_local_part(value: str) -> str:
    """Normalise a mailbox/alias name the same way the service layer does.

    Raises ``forms.ValidationError`` with the same user-safe messages, so bad
    input (``hhh@jihu``, spaces, uppercase) is rejected on the form instead of
    only after a service call.
    """
    local = (value or '').strip().lower()
    if not _LOCAL_PART_RE.match(local):
        raise forms.ValidationError(
            'Use 1-64 letters, numbers, dots, hyphens, underscores or plus signs; '
            'start and end with a letter or number.'
        )
    if '..' in local:
        raise forms.ValidationError('A name cannot contain two dots in a row.')
    return local


class MailboxCreateForm(forms.Form):
    local_part = forms.CharField(max_length=64, strip=True)
    domain = forms.CharField(max_length=255, strip=True)
    quota_mb = forms.IntegerField(min_value=0, required=False)
    is_admin = forms.BooleanField(required=False)
    # Where the owner receives the setup link and getting-started instructions
    # (an address they can already read). Blank = show the link to copy instead.
    send_to = forms.EmailField(max_length=255, required=False)

    def clean_local_part(self) -> str:
        return clean_local_part(self.cleaned_data.get('local_part', ''))

    def clean_domain(self) -> str:
        return (self.cleaned_data.get('domain') or '').strip().lower()

    def clean(self) -> dict:
        cleaned = super().clean()
        send_to = (cleaned.get('send_to') or '').strip().lower()
        cleaned['send_to'] = send_to
        if send_to and send_to == f'{cleaned.get("local_part")}@{cleaned.get("domain")}':
            # The owner cannot read the new mailbox before they have a password.
            self.add_error(
                'send_to', 'Use an address the owner can already read, not the new mailbox.'
            )
        return cleaned

    @property
    def quota_bytes(self) -> int:
        """Blank = the 1024 MB default; explicit 0 = unlimited."""
        quota_mb = self.cleaned_data.get('quota_mb')
        if quota_mb is None:
            return DEFAULT_QUOTA_BYTES
        return int(quota_mb) * _MB


class MailboxActionForm(forms.Form):
    ACTIONS = ('invite', 'quota', 'enable', 'disable', 'delete', 'grant_admin', 'revoke_admin')

    action = forms.ChoiceField(choices=[(a, a) for a in ACTIONS])
    address = forms.CharField(max_length=255, strip=True)
    quota_mb = forms.IntegerField(min_value=0, required=False)
    # Where the invite link should be shown: '' (flash message, default) or 'profile'.
    return_to = forms.CharField(max_length=16, strip=True, required=False)
    # Invite only: email the link here instead of showing it (see MailboxCreateForm).
    send_to = forms.EmailField(max_length=255, required=False)

    def clean(self) -> dict:
        cleaned = super().clean()
        send_to = (cleaned.get('send_to') or '').strip().lower()
        cleaned['send_to'] = send_to
        if send_to and send_to == (cleaned.get('address') or '').lower():
            self.add_error(
                'send_to', 'Use an address the owner can already read, not the mailbox itself.'
            )
        return cleaned

    @property
    def quota_bytes(self) -> int:
        """Blank = the 1024 MB default; explicit 0 = unlimited."""
        quota_mb = self.cleaned_data.get('quota_mb')
        if quota_mb is None:
            return DEFAULT_QUOTA_BYTES
        return int(quota_mb) * _MB


class SessionRevokeForm(forms.Form):
    """Revoke one (or, with ``all`` set, all) of a profile's sessions."""

    mailbox_id = forms.UUIDField()
    session_key = forms.CharField(max_length=64, strip=True, required=False)
    revoke_all = forms.BooleanField(required=False)


class RoleChangeForm(forms.Form):
    """Assign a named role (or clear to legacy staff) for one login."""

    address = forms.CharField(max_length=255, strip=True)
    role = forms.CharField(max_length=64, strip=True, required=False)


class TokenCreateForm(forms.Form):
    """Mint a scoped API token for one login (plaintext shown once).

    A key that can send mail also names its allowed senders, which this form has no field for:
    those are created on the API keys page.
    """

    address = forms.CharField(max_length=255, strip=True)
    name = forms.CharField(max_length=64, strip=True)
    scopes = forms.MultipleChoiceField(required=False)
    expires_in_days = forms.IntegerField(min_value=1, max_value=90)

    def __init__(self, *args: object, **kwargs: object) -> None:
        from backend.apps.accounts.services.tokens import SEND_SCOPE
        from backend.apps.accounts.types.permissions import TOKEN_SCOPES

        super().__init__(*args, **kwargs)
        self.fields['scopes'].choices = [(c, c) for c in TOKEN_SCOPES if c != SEND_SCOPE]


class TokenActionForm(forms.Form):
    """Rotate or revoke one of a login's tokens."""

    address = forms.CharField(max_length=255, strip=True)
    token_id = forms.UUIDField()
    action = forms.ChoiceField(choices=[('rotate', 'rotate'), ('revoke', 'revoke')])


class ApiKeyCreateForm(forms.Form):
    """Create an API key for an integration (secret shown once)."""

    name = forms.CharField(max_length=64, strip=True)
    scopes = forms.MultipleChoiceField(required=False)
    expires_in_days = forms.IntegerField(min_value=1, max_value=90)
    networks = forms.CharField(required=False, strip=True, widget=forms.Textarea)
    rate_limit_per_minute = forms.IntegerField(required=False, min_value=1, max_value=6000)
    senders = forms.CharField(required=False, strip=True, widget=forms.Textarea)
    send_limit_per_day = forms.IntegerField(required=False, min_value=1, max_value=100000)

    def __init__(self, *args: object, **kwargs: object) -> None:
        from backend.apps.accounts.types.permissions import TOKEN_SCOPES

        super().__init__(*args, **kwargs)
        self.fields['scopes'].choices = [(code, code) for code in TOKEN_SCOPES]

    def clean_networks(self) -> list[str]:
        """One range per line or comma-separated; validated by the token service."""
        raw = self.cleaned_data.get('networks') or ''
        return [part.strip() for part in raw.replace(',', '\n').splitlines() if part.strip()]

    def clean_senders(self) -> list[str]:
        """One address (or *@domain) per line or comma-separated; checked by the token service."""
        raw = self.cleaned_data.get('senders') or ''
        return [part.strip() for part in raw.replace(',', '\n').splitlines() if part.strip()]


class ApiKeyActionForm(forms.Form):
    """Rotate (optionally keeping the old secret for a while) or revoke one key."""

    token_id = forms.UUIDField()
    action = forms.ChoiceField(choices=[('rotate', 'rotate'), ('revoke', 'revoke')])
    grace_hours = forms.IntegerField(required=False, min_value=0, max_value=168)


class MailboxSetupForm(forms.Form):
    """The mailbox owner sets their own password via a setup link."""

    password = forms.CharField(max_length=128, strip=False, widget=forms.PasswordInput)
    password2 = forms.CharField(max_length=128, strip=False, widget=forms.PasswordInput)

    def clean(self) -> dict:
        cleaned = super().clean()
        first, second = cleaned.get('password', ''), cleaned.get('password2', '')
        if first and second and first != second:
            raise forms.ValidationError('Passwords do not match.')
        return cleaned


class AliasCreateForm(forms.Form):
    local_part = forms.CharField(max_length=64, strip=True)
    domain = forms.CharField(max_length=255, strip=True)
    destination = forms.EmailField(max_length=255)

    def clean_local_part(self) -> str:
        return clean_local_part(self.cleaned_data.get('local_part', ''))

    @property
    def source(self) -> str:
        return f'{self.cleaned_data["local_part"].lower()}@{self.cleaned_data["domain"].lower()}'


class AliasDeleteForm(forms.Form):
    alias_id = forms.UUIDField()


class RegistrationToggleForm(forms.Form):
    open = forms.BooleanField(required=False)
