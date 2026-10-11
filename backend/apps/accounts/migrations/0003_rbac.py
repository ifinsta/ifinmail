import uuid

import django.db.models.deletion
from django.db import migrations, models


def _seeded() -> list[dict[str, object]]:
    # Frozen copy of accounts.types.permissions.SEED_ROLES at migration time.
    # Migrations must not import live code: future edits to the seed map must
    # come with their own data migration instead of changing this list.
    all_codes = [
        'console.access',
        'mail.manage',
        'dns.manage',
        'security.manage',
        'system.manage',
        'users.manage',
        'audit.view',
        'roles.manage',
        'setup.manage',
    ]
    return [
        {
            'key': 'owner',
            'name': 'Owner',
            'description': 'Full access, including role grants. Keep to one or two logins.',
            'permissions': list(all_codes),
            'is_system': True,
        },
        {
            'key': 'administrator',
            'name': 'Administrator',
            'description': 'Runs the mail system day to day. Cannot grant roles.',
            'permissions': [code for code in all_codes if code != 'roles.manage'],
            'is_system': True,
        },
        {
            'key': 'support',
            'name': 'Support',
            'description': 'Read-only triage: dashboard plus logs and audit trails.',
            'permissions': ['console.access', 'audit.view'],
            'is_system': True,
        },
    ]


def seed_roles(apps, schema_editor) -> None:  # noqa: ARG001
    role_model = apps.get_model('accounts', 'Role')
    for row in _seeded():
        role_model.objects.update_or_create(
            key=row['key'],
            defaults={
                'name': row['name'],
                'description': row['description'],
                'permissions': row['permissions'],
                'is_system': row['is_system'],
            },
        )


def unseed_roles(apps, schema_editor) -> None:  # noqa: ARG001
    role_model = apps.get_model('accounts', 'Role')
    role_model.objects.filter(key__in=[row['key'] for row in _seeded()]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0002_mfa'),
    ]

    operations = [
        migrations.CreateModel(
            name='Role',
            fields=[
                (
                    'id',
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ('key', models.SlugField(max_length=64, unique=True)),
                ('name', models.CharField(max_length=64)),
                ('description', models.TextField(blank=True, default='')),
                ('permissions', models.JSONField(default=list)),
                ('is_system', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'db_table': 'accounts_role',
            },
        ),
        migrations.AddField(
            model_name='mailuser',
            name='role',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='users',
                to='accounts.role',
            ),
        ),
        migrations.RunPython(seed_roles, unseed_roles),
    ]
