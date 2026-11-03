"""Give the Owner and Administrator roles the new marketing.send permission.

Logins without a role (legacy staff) and superusers already hold every code; this only updates
roles stored in the database, which do not pick up new codes on their own.
"""

from django.db import migrations

CODE = 'marketing.send'


def grant(apps, schema_editor) -> None:
    Role = apps.get_model('accounts', 'Role')
    for role in Role.objects.filter(key__in=('owner', 'administrator')):
        codes = list(role.permissions or [])
        if CODE not in codes:
            role.permissions = [*codes, CODE]
            role.save(update_fields=['permissions'])


def revoke(apps, schema_editor) -> None:
    Role = apps.get_model('accounts', 'Role')
    for role in Role.objects.filter(key__in=('owner', 'administrator')):
        role.permissions = [c for c in (role.permissions or []) if c != CODE]
        role.save(update_fields=['permissions'])


class Migration(migrations.Migration):
    dependencies = [('accounts', '0015_agents_permission')]
    operations = [migrations.RunPython(grant, revoke)]
