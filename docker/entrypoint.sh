#!/bin/sh
set -e

echo "Waiting for MariaDB and running migrations..."
i=0
until alembic upgrade head; do
  i=$((i + 1))
  if [ "$i" -ge 60 ]; then
    echo "Alembic failed after 60 attempts"
    exit 1
  fi
  echo "DB not ready (attempt $i), retry in 2s..."
  sleep 2
done

echo "Migrations OK. Starting uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
