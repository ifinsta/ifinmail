"""releases — forms for the console page (web flow: views → forms → services)."""

from __future__ import annotations

from django import forms

from backend.apps.core.releases.types import CHANNEL_VALUES, DEFAULT_CHANNEL

_CHANNELS = [(value, value) for value in CHANNEL_VALUES]

ACTIONS = (
    'withdraw',
    'restore',
    'mandatory_on',
    'mandatory_off',
    'rollout',
    'notes',
    'delete',
)


class ReleasePublishForm(forms.Form):
    file = forms.FileField(allow_empty_file=False)
    channel = forms.ChoiceField(choices=_CHANNELS, initial=DEFAULT_CHANNEL)
    notes = forms.CharField(required=False, max_length=4000, widget=forms.Textarea)
    mandatory = forms.BooleanField(required=False)
    rollout_percent = forms.IntegerField(min_value=0, max_value=100, initial=100, required=False)
    publish = forms.BooleanField(required=False, initial=True)

    def clean_rollout_percent(self) -> int:
        value = self.cleaned_data.get('rollout_percent')
        return 100 if value is None else int(value)


class ReleaseActionForm(forms.Form):
    platform = forms.CharField(max_length=16)
    channel = forms.ChoiceField(choices=_CHANNELS)
    version_code = forms.IntegerField(min_value=1)
    action = forms.ChoiceField(choices=[(a, a) for a in ACTIONS])
    rollout_percent = forms.IntegerField(min_value=0, max_value=100, required=False)
    notes = forms.CharField(required=False, max_length=4000)


__all__ = ['ACTIONS', 'ReleaseActionForm', 'ReleasePublishForm']
