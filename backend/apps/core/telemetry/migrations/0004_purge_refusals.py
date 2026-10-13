"""Scanner refusals (DisallowedHost, 404s) are no longer recorded as errors; drop the backlog."""

from django.db import migrations

REFUSED = ('DisallowedHost', 'Resolver404', 'Http404')


def purge(apps, schema_editor):
    event = apps.get_model('ifinmail_telemetry', 'ErrorEvent')
    fingerprint = apps.get_model('ifinmail_telemetry', 'ErrorFingerprint')
    event.objects.filter(exc_type__in=REFUSED).delete()
    fingerprint.objects.filter(exc_type__in=REFUSED, events__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('ifinmail_telemetry', '0003_known_place'),
    ]

    operations = [
        migrations.RunPython(purge, migrations.RunPython.noop),
    ]
