#!/bin/bash
set -e
alembic upgrade dfa2f2e1adb2
exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}
