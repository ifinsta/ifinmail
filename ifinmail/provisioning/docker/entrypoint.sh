#!/bin/sh
set -e

echo "=== ifinmail entrypoint ==="

# Wait for PostgreSQL to be ready
echo "Waiting for PostgreSQL..."
until python - <<'PY' 2>/dev/null
import os
import psycopg

psycopg.connect(
    dbname=os.environ["DB_NAME"],
    user=os.environ["DB_USER"],
    password=os.environ["DB_PASSWORD"],
    host=os.environ["DB_HOST"],
    port=os.environ.get("DB_PORT", "5432"),
).close()
PY
do
    echo "  PostgreSQL not ready, retrying in 2s..."
    sleep 2
done
echo "  PostgreSQL is ready."

# Run Django checks
python manage.py check --deploy

# Apply database migrations
echo "Running migrations..."
python manage.py migrate --noinput

# Create superuser if it doesn't exist (idempotent)
if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ] && [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
    echo "Ensuring superuser '${DJANGO_SUPERUSER_USERNAME}' exists..."
    python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
username = '${DJANGO_SUPERUSER_USERNAME}'
email = '${DJANGO_SUPERUSER_EMAIL:-admin@example.com}'
password = '${DJANGO_SUPERUSER_PASSWORD}'
if not User.objects.filter(username=username).exists():
    User.objects.create_superuser(username=username, email=email, password=password)
    print('Superuser created.')
else:
    print('Superuser already exists.')
"
fi

# Collect static files
echo "Collecting static files..."
python manage.py collectstatic --noinput --clear

# Ensure nginx (nobody user) can read static files from shared volume
chown -R nobody:nogroup /app/staticfiles 2>/dev/null || true
chmod -R 755 /app/staticfiles

echo "=== Starting ifinmail ==="
exec "$@"
