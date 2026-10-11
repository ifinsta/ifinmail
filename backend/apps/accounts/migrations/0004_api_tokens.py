import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0003_rbac'),
    ]

    operations = [
        migrations.CreateModel(
            name='APIToken',
            fields=[
                (
                    'id',
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ('name', models.CharField(max_length=64)),
                ('prefix', models.CharField(max_length=16, unique=True)),
                ('token_hash', models.CharField(max_length=64)),
                ('scopes', models.JSONField(default=list)),
                ('expires_at', models.DateTimeField(blank=True, null=True)),
                ('last_used_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                (
                    'user',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='api_tokens',
                        to='accounts.mailuser',
                    ),
                ),
            ],
            options={
                'db_table': 'accounts_api_token',
            },
        ),
    ]
