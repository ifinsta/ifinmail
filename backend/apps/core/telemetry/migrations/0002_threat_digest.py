"""Threat digest: an hourly slim summary and the findings that carry a threat."""

import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('ifinmail_telemetry', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='ThreatDigest',
            fields=[
                (
                    'id',
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('hour', models.DateTimeField(unique=True)),
                ('summary', models.JSONField(default=dict)),
                ('findings_count', models.PositiveIntegerField(default=0)),
                ('top_severity', models.PositiveSmallIntegerField(default=0)),
                ('gist', models.TextField(blank=True, default='')),
                ('gist_source', models.CharField(default='rules', max_length=16)),
                ('priorities', models.JSONField(default=list)),
                ('correlations', models.JSONField(default=list)),
                ('ignored', models.JSONField(default=list)),
                ('tokens', models.PositiveIntegerField(default=0)),
                ('summarised_at', models.DateTimeField(blank=True, null=True)),
            ],
            options={'db_table': 'ifinmail_threat_digest', 'ordering': ['-hour']},
        ),
        migrations.CreateModel(
            name='ThreatFinding',
            fields=[
                (
                    'id',
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('key', models.CharField(max_length=190, unique=True)),
                ('kind', models.CharField(max_length=40)),
                ('severity', models.PositiveSmallIntegerField(default=0)),
                ('subject', models.CharField(blank=True, default='', max_length=190)),
                ('title', models.CharField(max_length=200)),
                ('summary', models.TextField(blank=True, default='')),
                ('count', models.PositiveIntegerField(default=0)),
                ('first_seen', models.DateTimeField()),
                ('last_seen', models.DateTimeField(db_index=True)),
                ('evidence', models.JSONField(default=list)),
                ('samples', models.JSONField(default=list)),
                ('tighten', models.JSONField(default=list)),
                ('status', models.CharField(db_index=True, default='open', max_length=16)),
                ('notified_at', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'db_table': 'ifinmail_threat_finding',
                'ordering': ['-severity', '-last_seen'],
            },
        ),
    ]
