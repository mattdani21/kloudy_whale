# Root Dockerfile for Railway (builds from repo root; app lives in swarm-harness/)
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

COPY swarm-harness/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY swarm-harness/app/ ./app/
COPY swarm-harness/worker/ ./worker/

# Single worker: builds execute in-process, so one predictable process per container
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
