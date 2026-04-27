#!/bin/bash
set -e
echo "=== PHASE 1: container started, PORT=${PORT} ==="
echo "=== PHASE 2: running alembic ==="
alembic upgrade head && echo "=== PHASE 3: alembic OK, starting uvicorn ===" || echo "=== ALEMBIC FAILED ==="
exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}
