#!/bin/sh
# Container entrypoint: run the durability worker alongside the API.
# The worker rescues builds orphaned by restarts (see worker/consumer.py).
set -e
python worker/consumer.py &
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 2
