"""
seguridad.py -> El SQL que escribe un LLM NUNCA se ejecuta tal cual.

Defensa en capas (si una falla, la siguiente para el golpe):
  1. Esta validación: una sola sentencia, de lectura (SELECT / WITH), sin palabras peligrosas
     y solo sobre las tablas permitidas.
  2. Un LÍMITE de filas: se envuelve la consulta en  SELECT * FROM (...) LIMIT n.
  3. En la base de datos (bd.py): un usuario de SOLO LECTURA que solo ve los esquemas marts y ml,
     sin las columnas con datos personales, en una transacción de solo lectura y con un tiempo
     máximo por consulta.
"""
import re

LIMITE_FILAS = 500

# Sentencias y funciones que no pueden aparecer en ningún caso
PROHIBIDAS = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|create|truncate|grant|revoke|copy|call|do|execute|"
    r"vacuum|analyze|cluster|reindex|refresh|comment|lock|listen|notify|prepare|deallocate|set|reset|"
    r"pg_sleep\w*|pg_read_\w+|pg_ls_\w+|pg_terminate_backend|pg_cancel_backend|lo_\w+|dblink\w*|"
    r"current_setting|set_config|into)\b",
    re.IGNORECASE,
)
ESQUEMAS_PERMITIDOS = {"marts", "ml"}


class SQLNoPermitido(ValueError):
    """El SQL generado no pasa la validación."""


def quitar_comentarios_y_textos(sql: str) -> str:
    """Quita comentarios y el contenido de los textos entre comillas (para no confundir 'drop' con DROP)."""
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


def validar(sql: str) -> str:
    """Devuelve el SQL limpio (sin ';' final) o lanza SQLNoPermitido explicando por qué."""
    if not sql or not sql.strip():
        raise SQLNoPermitido("La consulta está vacía")
    sql = sql.strip().rstrip(";").strip()
    limpio = quitar_comentarios_y_textos(sql)

    if ";" in limpio:
        raise SQLNoPermitido("Solo se permite una sentencia")
    if not re.match(r"^\s*(select|with)\b", limpio, re.IGNORECASE):
        raise SQLNoPermitido("Solo se permiten consultas de lectura (SELECT o WITH)")
    prohibida = PROHIBIDAS.search(limpio)
    if prohibida:
        raise SQLNoPermitido(f"Palabra no permitida: {prohibida.group(0).upper()}")

    # Cualquier "esquema.tabla" tiene que ser de un esquema permitido
    for esquema in re.findall(r"\b(?:from|join)\s+([a-z_][a-z0-9_]*)\s*\.", limpio, re.IGNORECASE):
        if esquema.lower() not in ESQUEMAS_PERMITIDOS:
            raise SQLNoPermitido(f"No se puede consultar el esquema '{esquema}'")
    if re.search(r"\b(pg_catalog|information_schema|pg_[a-z_]+)\s*\.", limpio, re.IGNORECASE):
        raise SQLNoPermitido("No se pueden consultar las tablas del sistema")
    return sql


def con_limite(sql: str, limite: int = LIMITE_FILAS) -> str:
    """Envuelve la consulta para que nunca devuelva más de `limite` filas."""
    return f"SELECT * FROM (\n{sql}\n) AS consulta_asistente\nLIMIT {int(limite)}"
