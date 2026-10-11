"""Give every mailbox still on the old default (0 = unlimited) the new 1024 MB default.

The mailboxes table is managed by init-db.sh (``managed = False``), so this runs
raw SQL and is a no-op when the table is absent (fresh test databases). An
administrator who wants a specific mailbox unlimited can set 0 again from the
console; the migration only rewrites rows that never left the old default.
"""

from django.db import migrations

DEFAULT_QUOTA_BYTES = 1024 * 1024 * 1024  # keep in sync with mail.types.quota


def backfill_default_quota(apps, schema_editor) -> None:
    connection = schema_editor.connection
    if 'mailboxes' not in connection.introspection.table_names():
        return
    with connection.cursor() as cursor:
        cursor.execute(
            'UPDATE mailboxes SET quota_bytes = %s WHERE quota_bytes = 0 OR quota_bytes IS NULL',
            [DEFAULT_QUOTA_BYTES],
        )
        updated = cursor.rowcount
    if updated:
        print(f'  mail: {updated} mailbox(es) moved from unlimited to the 1024 MB default')


class Migration(migrations.Migration):
    dependencies = [
        ('mail', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(backfill_default_quota, migrations.RunPython.noop),
    ]
