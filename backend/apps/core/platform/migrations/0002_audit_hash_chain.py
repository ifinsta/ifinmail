"""Tamper-evident audit trail: sequence number and hash link per event."""

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('ifinmail_services', '0001_initial')]

    operations = [
        migrations.AlterField(
            model_name='auditevent',
            name='time',
            field=models.DateTimeField(db_index=True, default=django.utils.timezone.now),
        ),
        migrations.AddField(
            model_name='auditevent',
            name='seq',
            field=models.BigIntegerField(blank=True, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='auditevent',
            name='prev_hash',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='auditevent',
            name='entry_hash',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
    ]
