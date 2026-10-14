import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0011_passkeys'),
    ]

    operations = [
        migrations.CreateModel(
            name='UserProfile',
            fields=[
                (
                    'user',
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name='profile',
                        serialize=False,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ('photo_large', models.BinaryField(blank=True, null=True)),
                ('photo_small', models.BinaryField(blank=True, null=True)),
                ('photo_sha256', models.CharField(blank=True, default='', max_length=64)),
                ('photo_updated_at', models.DateTimeField(blank=True, null=True)),
                ('directory_hidden', models.BooleanField(default=False)),
            ],
            options={
                'db_table': 'accounts_user_profile',
            },
        ),
    ]
