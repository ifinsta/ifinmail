import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0012_user_profile'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='password_login_disabled',
            field=models.BooleanField(default=False),
        ),
        migrations.CreateModel(
            name='PasskeyRecoveryCode',
            fields=[
                (
                    'id',
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ('code_hash', models.CharField(max_length=128)),
                ('used_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                (
                    'user',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='passkey_recovery_codes',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                'db_table': 'accounts_passkey_recovery_code',
                'ordering': ['created_at'],
            },
        ),
    ]
