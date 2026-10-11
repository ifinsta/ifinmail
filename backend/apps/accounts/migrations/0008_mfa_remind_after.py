"""State-only: the users table is unmanaged (owned by init-db.sh / db-upgrade.sql).

The mfa_remind_after column is added there; this migration only keeps the Django model state
in sync.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0007_password_change_required'),
    ]

    operations = [
        migrations.AddField(
            model_name='mailuser',
            name='mfa_remind_after',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
