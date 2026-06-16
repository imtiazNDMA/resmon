# syntax=docker/dockerfile:1
# Self-hosted MLflow tracking server with a Postgres backend store (plan 01 T-07).
FROM python:3.13-slim

RUN pip install --no-cache-dir "mlflow>=2.14" "psycopg2-binary>=2.9"
RUN useradd --create-home --uid 10002 mlflow
USER mlflow
EXPOSE 5000

# Shell form so the env-var backend/artifact URIs expand at runtime.
CMD mlflow server --host 0.0.0.0 --port 5000 \
    --backend-store-uri "$MLFLOW_BACKEND_STORE_URI" \
    --artifacts-destination "$MLFLOW_ARTIFACT_ROOT"
