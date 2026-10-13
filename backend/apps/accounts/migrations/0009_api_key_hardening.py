"""API keys: rotation overlap, network allow-list, per-key rate limit, last-used address."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0008_mfa_remind_after'),
    ]

    operations = [
        migrations.AddField(
            model_name='apitoken',
            name='last_used_ip',
            field=models.GenericIPAddressField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='apitoken',
            name='previous_hash',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='apitoken',
            name='previous_expires_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='apitoken',
            name='allowed_networks',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='apitoken',
            name='rate_limit_per_minute',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
