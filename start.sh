#!/bin/bash
set -e
alembic upgrade heads
exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}
