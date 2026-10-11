"""Forms for the DNS server pages."""

from __future__ import annotations

from django import forms

from ..types.zones import RecordType, ZoneMode


class ZoneForm(forms.Form):
    zone = forms.CharField(max_length=255, strip=True)


class RecordAddForm(forms.Form):
    zone = forms.CharField(max_length=255, strip=True)
    name = forms.CharField(max_length=255, strip=True, required=False)
    rtype = forms.ChoiceField(choices=[(t.value, t.value) for t in RecordType])
    value = forms.CharField(max_length=2100, strip=True)
    ttl = forms.IntegerField(min_value=60, max_value=86400, required=False, initial=3600)
    priority = forms.IntegerField(min_value=0, max_value=65535, required=False)


class RecordDeleteForm(forms.Form):
    zone = forms.CharField(max_length=255, strip=True)
    record_id = forms.UUIDField()


class ZoneModeForm(forms.Form):
    zone = forms.CharField(max_length=255, strip=True)
    mode = forms.ChoiceField(choices=[(m.value, m.value) for m in ZoneMode])


class SecondariesForm(forms.Form):
    addresses = forms.CharField(max_length=2000, required=False, strip=True)

    def address_list(self) -> list[str]:
        raw = self.cleaned_data.get('addresses', '')
        return [part for chunk in raw.splitlines() for part in chunk.replace(',', ' ').split()]
