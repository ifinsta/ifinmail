import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies: list = []

    operations = [
        migrations.CreateModel(
            name='PluginInstallation',
            fields=[
                (
                    'id',
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('plugin_id', models.CharField(max_length=40, unique=True)),
                ('version', models.CharField(max_length=20)),
                (
                    'source',
                    models.CharField(
                        choices=[('bundled', 'bundled'), ('submitted', 'submitted')], max_length=16
                    ),
                ),
                ('manifest', models.TextField()),
                ('settings', models.JSONField(default=dict)),
                (
                    'state',
                    models.CharField(
                        choices=[
                            ('installing', 'installing'),
                            ('enabled', 'enabled'),
                            ('disabled', 'disabled'),
                            ('applying', 'applying'),
                            ('uninstalling', 'uninstalling'),
                            ('failed', 'failed'),
                        ],
                        db_index=True,
                        max_length=16,
                    ),
                ),
                ('target_state', models.CharField(blank=True, default='', max_length=16)),
                ('pending_operation', models.CharField(blank=True, default='', max_length=16)),
                ('last_error', models.TextField(blank=True, default='')),
                ('revision', models.PositiveIntegerField(default=1)),
                ('installed_by', models.CharField(blank=True, default='', max_length=255)),
            ],
            options={'db_table': 'plugin_installation', 'ordering': ['plugin_id']},
        ),
        migrations.CreateModel(
            name='PluginSubmission',
            fields=[
                (
                    'id',
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('plugin_id', models.CharField(db_index=True, max_length=40)),
                ('version', models.CharField(max_length=20)),
                ('name', models.CharField(max_length=60)),
                ('manifest', models.TextField()),
                ('manifest_sha256', models.CharField(max_length=64)),
                (
                    'state',
                    models.CharField(
                        choices=[
                            ('submitted', 'submitted'),
                            ('approved', 'approved'),
                            ('rejected', 'rejected'),
                            ('withdrawn', 'withdrawn'),
                            ('retired', 'retired'),
                        ],
                        db_index=True,
                        default='submitted',
                        max_length=16,
                    ),
                ),
                ('submitted_by', models.CharField(max_length=255)),
                ('submitter_note', models.TextField(blank=True, default='')),
                ('reviewed_by', models.CharField(blank=True, default='', max_length=255)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('review_note', models.TextField(blank=True, default='')),
            ],
            options={'db_table': 'plugin_submission', 'ordering': ['-created_at']},
        ),
        migrations.AddConstraint(
            model_name='pluginsubmission',
            constraint=models.UniqueConstraint(
                condition=models.Q(('state__in', ['approved', 'retired', 'submitted'])),
                fields=('plugin_id', 'version'),
                name='plugin_submission_live_version_unique',
            ),
        ),
    ]
