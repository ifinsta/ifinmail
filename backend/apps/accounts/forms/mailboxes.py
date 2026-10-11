"""Forms for the Mailboxes and Aliases pages."""

from __future__ import annotations

import re

from django import forms

_MB = 1024 * 1024
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
    quota_mb = forms.IntegerField(min_value=0, required=False, initial=0)
    is_admin = forms.BooleanField(required=False)

    def clean_local_part(self) -> str:
        return clean_local_part(self.cleaned_data.get('local_part', ''))

    def clean_domain(self) -> str:
        return (self.cleaned_data.get('domain') or '').strip().lower()

    @property
    def quota_bytes(self) -> int:
        return int(self.cleaned_data.get('quota_mb') or 0) * _MB


class MailboxActionForm(forms.Form):
    ACTIONS = ('invite', 'quota', 'enable', 'disable', 'delete')

    action = forms.ChoiceField(choices=[(a, a) for a in ACTIONS])
    address = forms.CharField(max_length=255, strip=True)
    quota_mb = forms.IntegerField(min_value=0, required=False)

    @property
    def quota_bytes(self) -> int:
        return int(self.cleaned_data.get('quota_mb') or 0) * _MB


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
