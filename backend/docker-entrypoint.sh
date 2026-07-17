#!/bin/sh
set -e

alembic upgrade head

# $PORT is injected by the hosting platform (e.g. Railway); 8000 is the
# canonical local-dev fallback — see docker-compose.yml and .env.example.
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
