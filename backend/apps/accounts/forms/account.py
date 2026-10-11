"""Forms for the self-service Account page."""

from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _

from ..services.profile import MIN_PASSWORD_LENGTH


class ProfileNameForm(forms.Form):
    full_name = forms.CharField(max_length=128, strip=True)


class AccountPasswordForm(forms.Form):
    old_password = forms.CharField(max_length=128, strip=False)
    new_password = forms.CharField(max_length=128, strip=False, min_length=MIN_PASSWORD_LENGTH)
    confirm_password = forms.CharField(max_length=128, strip=False)

    def clean(self) -> dict[str, str]:
        cleaned = super().clean()
        new = cleaned.get('new_password')
        confirm = cleaned.get('confirm_password')
        if new and confirm and new != confirm:
            self.add_error('confirm_password', forms.ValidationError(_('Passwords do not match.')))
        return cleaned
