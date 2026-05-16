#!/bin/sh
set -e

echo "=== ifinmail entrypoint ==="

# Wait for PostgreSQL to be ready
echo "Waiting for PostgreSQL..."
until python -c "import psycopg2; psycopg2.connect('${DATABASE_URL}')" 2>/dev/null; do
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
