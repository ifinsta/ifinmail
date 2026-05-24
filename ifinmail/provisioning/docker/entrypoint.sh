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

# Collect static files
echo "Collecting static files..."
python manage.py collectstatic --noinput --clear

echo "=== Starting ifinmail ==="
exec "$@"
