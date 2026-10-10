"""Forms for the Mailboxes and Aliases pages."""

from __future__ import annotations

from django import forms

_MB = 1024 * 1024


class MailboxCreateForm(forms.Form):
    local_part = forms.CharField(max_length=64, strip=True)
    domain = forms.CharField(max_length=255, strip=True)
    password = forms.CharField(max_length=128, strip=False)
    quota_mb = forms.IntegerField(min_value=0, required=False, initial=0)
    is_admin = forms.BooleanField(required=False)

    @property
    def quota_bytes(self) -> int:
        return int(self.cleaned_data.get('quota_mb') or 0) * _MB


class MailboxActionForm(forms.Form):
    ACTIONS = ('password', 'quota', 'enable', 'disable', 'delete')

    action = forms.ChoiceField(choices=[(a, a) for a in ACTIONS])
    address = forms.CharField(max_length=255, strip=True)
    password = forms.CharField(max_length=128, strip=False, required=False)
    quota_mb = forms.IntegerField(min_value=0, required=False)

    @property
    def quota_bytes(self) -> int:
        return int(self.cleaned_data.get('quota_mb') or 0) * _MB


class AliasCreateForm(forms.Form):
    local_part = forms.CharField(max_length=64, strip=True)
    domain = forms.CharField(max_length=255, strip=True)
    destination = forms.EmailField(max_length=255)

    @property
    def source(self) -> str:
        return f'{self.cleaned_data["local_part"].lower()}@{self.cleaned_data["domain"].lower()}'


class AliasDeleteForm(forms.Form):
    alias_id = forms.UUIDField()


class RegistrationToggleForm(forms.Form):
    open = forms.BooleanField(required=False)
