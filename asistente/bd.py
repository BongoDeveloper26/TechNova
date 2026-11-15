"""
bd.py -> Base de datos del asistente.

  - Crea (o actualiza) el usuario de SOLO LECTURA con el que se ejecuta el SQL del LLM:
      * solo puede leer los esquemas marts y ml del data warehouse
      * NO ve las columnas con datos personales de los clientes (nombre, email, fecha de nacimiento)
      * todas sus transacciones son de solo lectura y cada consulta tiene un tiempo máximo
  - Crea la tabla asistente.consulta, donde se registra cada pregunta (para medir y mejorar)
  - Ejecuta las consultas con ese usuario

Se llama en cada arranque del asistente: es idempotente, y así sobrevive a un
reiniciar_todo.py o a un dbt build (que vuelven a crear las tablas desde cero).
"""
import os
import sys
import time
from pathlib import Path

import psycopg
from psycopg import sql as psql

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "etl"))

from conexiones import conectar_dw, nombre_dw  # noqa: E402

USUARIO_LECTOR = os.getenv("ASISTENTE_DB_USER", "technova_lector")
TIEMPO_MAXIMO_CONSULTA = "15s"
ESQUEMAS = ["marts", "ml"]
TABLAS_EXCLUIDAS = {"ml.ejecucion"}                   # metadatos internos, no aportan al usuario
COLUMNAS_PRIVADAS = {"marts.dim_cliente": {"nombre_completo", "email", "fecha_nacimiento"}}


def clave_lector() -> str:
    return os.getenv("ASISTENTE_DB_PASSWORD") or os.getenv("POSTGRES_PASSWORD", "") + "_lector"


def tablas_visibles(conn) -> dict:
    """{'marts.fct_ventas': [('dia', 'date'), ...]} solo con lo que el asistente puede ver."""
    filas = conn.execute("""
        SELECT table_schema || '.' || table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = ANY(%s)
        ORDER BY table_schema, table_name, ordinal_position
    """, (ESQUEMAS,)).fetchall()
    tablas = {}
    for tabla, columna, tipo in filas:
        if tabla in TABLAS_EXCLUIDAS or columna in COLUMNAS_PRIVADAS.get(tabla, set()):
            continue
        tablas.setdefault(tabla, []).append((columna, tipo))
    return tablas


def preparar():
    """Usuario de solo lectura con permisos mínimos + tabla de registro de preguntas."""
    with conectar_dw() as conn:
        existe = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (USUARIO_LECTOR,)).fetchone()
        accion = "ALTER" if existe else "CREATE"
        conn.execute(psql.SQL(f"{accion} ROLE {{}} LOGIN PASSWORD {{}}").format(
            psql.Identifier(USUARIO_LECTOR), psql.Literal(clave_lector())))
        lector = psql.Identifier(USUARIO_LECTOR)
        conn.execute(psql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(lector))
        conn.execute(psql.SQL("ALTER ROLE {} SET statement_timeout = {}").format(
            lector, psql.Literal(TIEMPO_MAXIMO_CONSULTA)))
        conn.execute(psql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(psql.Identifier(nombre_dw()), lector))

        tablas = tablas_visibles(conn)
        existentes = {f[0] for f in conn.execute(
            "SELECT schema_name FROM information_schema.schemata WHERE schema_name = ANY(%s)", (ESQUEMAS,))}
        for esquema in [e for e in ESQUEMAS if e in existentes]:   # ml no existe hasta entrenar los modelos
            e = psql.Identifier(esquema)
            conn.execute(psql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(e, lector))
            conn.execute(psql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA {} FROM {}").format(e, lector))
        for tabla, columnas in tablas.items():
            esquema, nombre = tabla.split(".")
            # Permiso columna a columna: las privadas no se conceden
            conn.execute(psql.SQL("GRANT SELECT ({}) ON {}.{} TO {}").format(
                psql.SQL(", ").join(psql.Identifier(c) for c, _ in columnas),
                psql.Identifier(esquema), psql.Identifier(nombre), lector))

        conn.execute("""
            CREATE SCHEMA IF NOT EXISTS asistente;
            CREATE TABLE IF NOT EXISTS asistente.consulta (
                id_consulta  SERIAL PRIMARY KEY,
                momento      TIMESTAMPTZ NOT NULL DEFAULT now(),
                proveedor    VARCHAR(20),
                modelo       VARCHAR(60),
                pregunta     TEXT NOT NULL,
                sql_generado TEXT,
                intentos     SMALLINT,
                filas        INTEGER,
                correcta     BOOLEAN,
                error        TEXT,
                segundos     NUMERIC(6,2)
            );
        """)
    return len(tablas)


def conectar_lector():
    return psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"), port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=nombre_dw(), user=USUARIO_LECTOR, password=clave_lector(),
    )


def ejecutar(sql_texto: str):
    """Ejecuta una consulta con el usuario de solo lectura. Devuelve (columnas, filas)."""
    with conectar_lector() as conn:
        conn.read_only = True
        cursor = conn.execute(sql_texto)
        return [c.name for c in cursor.description], cursor.fetchall()


def registrar(respuesta, proveedor, modelo):
    try:
        with conectar_dw() as conn:
            conn.execute("""
                INSERT INTO asistente.consulta
                    (proveedor, modelo, pregunta, sql_generado, intentos, filas, correcta, error, segundos)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (proveedor, modelo, respuesta.pregunta, respuesta.sql, respuesta.intentos,
                  len(respuesta.filas) if respuesta.filas is not None else None,
                  respuesta.error is None, respuesta.error, round(respuesta.segundos, 2)))
    except psycopg.Error:
        pass   # el registro nunca debe impedir contestar


def esperar_bd(segundos=30):
    """En Docker la base de datos puede tardar en arrancar."""
    limite = time.time() + segundos
    while True:
        try:
            with conectar_dw():
                return
        except psycopg.OperationalError:
            if time.time() > limite:
                raise
            time.sleep(2)