#!/bin/bash
set -e
find /app -name "*.pyc" -delete
find /app -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
alembic upgrade 0003
exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}
