"""Forms for the Certificates and Network pages."""

from __future__ import annotations

from django import forms

_PEM_LIMIT = 64 * 1024


class CertificateActionForm(forms.Form):
    action = forms.ChoiceField(
        choices=[('issue', 'issue'), ('renew', 'renew'), ('letsencrypt', 'letsencrypt')]
    )


class CertificateUploadForm(forms.Form):
    certificate = forms.CharField(max_length=_PEM_LIMIT, strip=True)
    private_key = forms.CharField(max_length=_PEM_LIMIT, strip=True)


class EntryPointForm(forms.Form):
    key = forms.CharField(max_length=32)
    enabled = forms.BooleanField(required=False)


class BlockForm(forms.Form):
    cidr = forms.CharField(max_length=64, strip=True)
    note = forms.CharField(max_length=120, strip=True, required=False)


class ThreatBlockForm(forms.Form):
    """Block the network a Threats finding is about, for a while or until removed."""

    DURATIONS = ('1h', '24h', '7d', 'forever')
    finding = forms.CharField(max_length=64)
    duration = forms.ChoiceField(choices=[(d, d) for d in DURATIONS], initial='24h')


class AutoProtectForm(forms.Form):
    """Opt-in automatic blocking and flood mode (see ``threats.autoblock``)."""

    block = forms.BooleanField(required=False)
    flood = forms.BooleanField(required=False)
    hours = forms.IntegerField()
    allow = forms.CharField(required=False, max_length=4000, strip=True)


class UnblockForm(forms.Form):
    cidr = forms.CharField(max_length=64, strip=True)


class RateForm(forms.Form):
    per_minute = forms.IntegerField(min_value=0, max_value=100000)
