#!/usr/bin/env bash
# Arranque del contenedor de Airflow
set -euo pipefail

# 1. Airflow guarda su propia información (DAGs, ejecuciones, logs...) en una base de datos.
#    Usamos nuestro mismo PostgreSQL, en una base de datos aparte llamada "airflow".
python - <<'PY'
import os
import psycopg

with psycopg.connect(host=os.environ.get("POSTGRES_HOST", "postgres"),
                     port=int(os.environ.get("POSTGRES_PORT", "5432")), dbname=os.environ["POSTGRES_DB"],
                     user=os.environ["POSTGRES_USER"],
                     password=os.environ["POSTGRES_PASSWORD"], autocommit=True) as conn:
    if not conn.execute("SELECT 1 FROM pg_database WHERE datname = 'airflow'").fetchone():
        conn.execute("CREATE DATABASE airflow")
        print("Base de datos 'airflow' creada")
PY

# 2. "standalone" arranca todo Airflow en un solo contenedor: la web (api-server),
#    el planificador (scheduler), el lector de DAGs (dag-processor) y el triggerer.
#    Perfecto para desarrollo; en producción cada uno iría en su propio contenedor.
exec airflow standalone