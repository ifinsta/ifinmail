"""Sending through the API: allowed senders and a daily cap per key, and the ``mail.send`` code.

Roles are stored rows (see ``0003``), so the new permission code has to be added to the system
roles that are meant to hold everything: Owner and Administrator. Support never gets it.
"""

from django.db import migrations, models

HOLDERS = ('owner', 'administrator')
CODE = 'mail.send'


def grant(apps, schema_editor):
    Role = apps.get_model('accounts', 'Role')
    for role in Role.objects.filter(key__in=HOLDERS):
        codes = list(role.permissions or [])
        if CODE not in codes:
            codes.append(CODE)
            role.permissions = codes
            role.save(update_fields=['permissions'])


def revoke(apps, schema_editor):
    Role = apps.get_model('accounts', 'Role')
    for role in Role.objects.all():
        codes = [c for c in (role.permissions or []) if c != CODE]
        if codes != list(role.permissions or []):
            role.permissions = codes
            role.save(update_fields=['permissions'])


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0009_api_key_hardening'),
    ]

    operations = [
        migrations.AddField(
            model_name='apitoken',
            name='allowed_senders',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='apitoken',
            name='send_limit_per_day',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.RunPython(grant, revoke),
    ]
