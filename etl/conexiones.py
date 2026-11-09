"""
conexiones.py -> Conexiones a las dos bases de datos.

  - OLTP (technova):    la base de datos de la tienda. El ETL solo LEE de ella.
  - DW   (technova_dw): la base de datos analítica. El ETL ESCRIBE aquí.
"""
import os

import psycopg
from dotenv import load_dotenv

from configuracion import FICHERO_ESQUEMA_DW

load_dotenv()


def _conectar(dbname: str) -> psycopg.Connection:
    return psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=dbname,
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
    )


def nombre_dw() -> str:
    return os.getenv("DW_DB", "technova_dw")


def conectar_oltp() -> psycopg.Connection:
    return _conectar(os.getenv("POSTGRES_DB"))


def conectar_dw() -> psycopg.Connection:
    return _conectar(nombre_dw())


def preparar_dw():
    """Crea la base de datos analítica y sus tablas de control si no existen."""
    with conectar_oltp() as conn:
        conn.autocommit = True  # CREATE DATABASE no puede ir dentro de una transacción
        existe = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (nombre_dw(),)).fetchone()
        if not existe:
            conn.execute(f'CREATE DATABASE "{nombre_dw()}"')

    with conectar_dw() as conn:
        conn.execute(FICHERO_ESQUEMA_DW.read_text(encoding="utf-8"))