"""State-only: the users table is unmanaged (owned by init-db.sh / db-upgrade.sql).

The mfa_required column is added there with ALTER TABLE ... IF NOT EXISTS;
this migration only keeps the Django model state in sync.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0005_account_profile'),
    ]

    operations = [
        migrations.AddField(
            model_name='mailuser',
            name='mfa_required',
            field=models.BooleanField(default=True),
        ),
    ]
