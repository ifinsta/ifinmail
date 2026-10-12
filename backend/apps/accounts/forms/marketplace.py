"""Forms for the Marketplace (plugin settings are validated by the plugin services)."""

from __future__ import annotations

from django import forms

from backend.apps.core.plugins.types import MAX_MANIFEST_BYTES, Operation

SETTING_PREFIX = 'setting__'


class PluginActionForm(forms.Form):
    action = forms.ChoiceField(choices=[(op.value, op.value) for op in Operation])
    revision = forms.IntegerField(min_value=0, required=False)


class SubmitPluginForm(forms.Form):
    manifest = forms.CharField(max_length=MAX_MANIFEST_BYTES, required=False, strip=False)
    manifest_file = forms.FileField(required=False)
    note = forms.CharField(max_length=2000, required=False)

    def clean(self) -> dict:
        cleaned = super().clean()
        upload = cleaned.get('manifest_file')
        if upload is not None:
            if upload.size > MAX_MANIFEST_BYTES:
                raise forms.ValidationError('The file is larger than 32 KiB.')
            cleaned['manifest'] = upload.read()
        if not cleaned.get('manifest'):
            raise forms.ValidationError('Paste a plugin.toml or choose the file.')
        return cleaned


class SubmissionActionForm(forms.Form):
    action = forms.ChoiceField(
        choices=[(a, a) for a in ('approve', 'reject', 'withdraw', 'retire')]
    )
    note = forms.CharField(max_length=2000, required=False)
