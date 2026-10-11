"""State-only: the users table is unmanaged (owned by init-db.sh / db-upgrade.sql).

The full_name column is added there with ALTER TABLE ... IF NOT EXISTS; this
migration only keeps the Django model state in sync.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0004_api_tokens'),
    ]

    operations = [
        migrations.AddField(
            model_name='mailuser',
            name='full_name',
            field=models.CharField(blank=True, default='', max_length=128),
        ),
    ]
