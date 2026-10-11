"""State-only: the users table is unmanaged (owned by init-db.sh / db-upgrade.sql).

The password_change_required column is added there; this migration only keeps the Django
model state in sync.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0006_mfa_required'),
    ]

    operations = [
        migrations.AddField(
            model_name='mailuser',
            name='password_change_required',
            field=models.BooleanField(default=False),
        ),
    ]
