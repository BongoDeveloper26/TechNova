"""
asistente.py -> Responde preguntas en lenguaje natural sobre los datos de TechNova.

    "¿Qué tienda vendió más en noviembre?"
            │
            ▼
    1. El LLM recibe la pregunta + el contexto (tablas, métricas, reglas, ejemplos)
       y devuelve un JSON con el SQL, el tipo de gráfico y un título          (text-to-SQL)
    2. seguridad.py valida el SQL y le pone un límite de filas
    3. Se ejecuta con el usuario de SOLO LECTURA                                (bd.py)
         └─ si falla, el error vuelve al LLM para que corrija su SQL (1 reintento: autocorrección)
    4. El LLM resume los resultados en 2-4 frases, sin inventar nada que no esté en ellos
    5. Se registra todo en asistente.consulta (pregunta, SQL, si funcionó, tiempo...)

Uso desde código:
    from asistente import preguntar
    r = preguntar("¿Cuánto facturó la web en 2025?")
    print(r.texto, r.sql, r.columnas, r.filas)
"""
import json
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

import psycopg
import sqlparse

import bd
import llm
from esquema import contexto
from seguridad import SQLNoPermitido, con_limite, validar

MAX_INTENTOS = 2           # el primero + 1 autocorrección
FILAS_PARA_RESUMEN = 25    # el LLM resume a partir de las primeras filas (no hace falta mandarlo todo)
GRAFICOS = {"barras", "lineas", "tarta", "ninguno"}

EJEMPLOS = [
    ("¿Cuánto facturó cada canal en 2025?",
     {"sql": "SELECT v.canal, ROUND(SUM(v.importe_neto), 2) AS facturacion\nFROM marts.fct_ventas v\n"
             "WHERE v.dia BETWEEN '2025-01-01' AND '2025-12-31'\nGROUP BY v.canal\nORDER BY facturacion DESC",
      "grafico": "tarta", "titulo": "Facturación por canal en 2025"}),
    ("Top 5 productos más vendidos en la tienda de Gran Vía en noviembre de 2025",
     {"sql": "SELECT p.producto, SUM(v.cantidad) AS unidades, ROUND(SUM(v.importe_neto), 2) AS facturacion\n"
             "FROM marts.fct_ventas v\nJOIN marts.dim_producto p ON p.id_producto = v.id_producto\n"
             "JOIN marts.dim_ubicacion u ON u.id_ubicacion = v.id_ubicacion\n"
             "WHERE u.ubicacion = 'TechNova Madrid Gran Vía' AND v.dia BETWEEN '2025-11-01' AND '2025-11-30'\n"
             "GROUP BY p.producto\nORDER BY unidades DESC\nLIMIT 5",
      "grafico": "barras", "titulo": "Top 5 productos en TechNova Madrid Gran Vía (noviembre 2025)"}),
    ("¿Cómo ha evolucionado el ticket medio mes a mes en 2025?",
     {"sql": "SELECT to_char(v.dia, 'YYYY-MM') AS mes,\n"
             "       ROUND(SUM(v.importe_neto) / COUNT(DISTINCT v.id_pedido), 2) AS ticket_medio\n"
             "FROM marts.fct_ventas v\nWHERE v.dia BETWEEN '2025-01-01' AND '2025-12-31'\n"
             "GROUP BY mes\nORDER BY mes",
      "grafico": "lineas", "titulo": "Ticket medio mensual en 2025"}),
    ("¿Cuántos empleados tiene la empresa en Marte?",
     {"sql": None, "grafico": "ninguno", "titulo": "",
      "explicacion": "TechNova no tiene centros en Marte: sus tiendas y almacenes están en España."}),
]


@dataclass
class Respuesta:
    pregunta: str
    texto: str = ""
    sql: str | None = None
    columnas: list = field(default_factory=list)
    filas: list | None = None
    grafico: str = "ninguno"
    titulo: str = ""
    intentos: int = 0
    error: str | None = None
    segundos: float = 0.0
    sql_fallidos: list = field(default_factory=list)   # SQL que dio error antes de la autocorrección


# ---------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------

def sistema_sql() -> str:
    ejemplos = "\n\n".join(f"Pregunta: {p}\nRespuesta: {json.dumps(r, ensure_ascii=False)}" for p, r in EJEMPLOS)
    return f"""Eres un analista de datos experto en SQL de PostgreSQL que trabaja para TechNova.
Conviertes preguntas en español en UNA consulta SQL de solo lectura sobre su data warehouse.

{contexto()}

FORMATO DE SALIDA: responde SOLO con un objeto JSON con estas claves:
- "sql": la consulta (una sola sentencia SELECT o WITH, con los nombres de tabla con su esquema),
         o null si la pregunta no se puede responder con estos datos
- "grafico": "barras" (comparar categorías), "lineas" (evolución en el tiempo), "tarta" (reparto de un total
             en pocas partes) o "ninguno" (un solo número o una tabla de detalle)
- "titulo": un título corto para el resultado
- "explicacion": solo si "sql" es null, explica brevemente por qué

EJEMPLOS:

{ejemplos}"""


SISTEMA_RESUMEN = """Eres un analista de datos de TechNova que explica resultados a personas de negocio.
Responde en español en 2 a 4 frases, directo y con las cifras clave.
- Usa SOLO los datos de los resultados: no inventes ni estimes nada que no esté en ellos.
- Formato español: 1.234.567,89 €; los valores en tanto por uno pásalos a porcentaje (0,253 -> 25,3 %).
- Si hay muchas filas, destaca lo más importante (el mayor, el menor, la tendencia).
- Si no hay resultados, dilo y sugiere cómo reformular la pregunta.
- No menciones el SQL ni los nombres de las tablas."""


def mensaje_sql(pregunta, historial, sql_fallido=None, error=None) -> str:
    partes = []
    if historial:
        # Para entender preguntas de seguimiento como "¿y en 2024?"
        partes.append("CONVERSACIÓN ANTERIOR (para entender referencias como 'y en 2024', 'de esos'...):")
        for anterior in historial[-3:]:
            partes.append(f"Pregunta: {anterior.pregunta}\nSQL: {anterior.sql or '(sin SQL)'}")
        partes.append("")
    partes.append(f"Pregunta: {pregunta}")
    if sql_fallido:
        partes.append(f"\nTu SQL anterior ha fallado:\n{sql_fallido}\nError: {error}\n"
                      "Corrígelo y devuelve de nuevo el JSON completo.")
    return "\n".join(partes)


def a_texto(valor):
    if isinstance(valor, Decimal):
        return float(round(valor, 4))
    if isinstance(valor, (date, datetime)):
        return valor.isoformat()
    return valor


def mensaje_resumen(r: Respuesta) -> str:
    filas = [dict(zip(r.columnas, map(a_texto, f))) for f in r.filas[:FILAS_PARA_RESUMEN]]
    resto = f"\n(se muestran {len(filas)} de {len(r.filas)} filas)" if len(r.filas) > len(filas) else ""
    return (f"Pregunta: {r.pregunta}\nTítulo del resultado: {r.titulo}\n"
            f"Resultados ({len(r.filas)} filas):\n{json.dumps(filas, ensure_ascii=False, default=str)}{resto}")


# ---------------------------------------------------------------------
# Proceso
# ---------------------------------------------------------------------

def generar_sql(pregunta, historial, sql_fallido=None, error=None) -> dict:
    datos = llm.extraer_json(llm.generar(sistema_sql(), mensaje_sql(pregunta, historial, sql_fallido, error),
                                         json_salida=True))
    grafico = str(datos.get("grafico") or "ninguno").lower()
    return {"sql": datos.get("sql"), "grafico": grafico if grafico in GRAFICOS else "ninguno",
            "titulo": datos.get("titulo") or "", "explicacion": datos.get("explicacion") or ""}


def preguntar(pregunta: str, historial: list | None = None, resumir: bool = True,
              registrar: bool = True) -> Respuesta:
    inicio = time.time()
    r = Respuesta(pregunta=pregunta.strip())
    sql_fallido = error = None
    try:
        for intento in range(1, MAX_INTENTOS + 1):
            r.intentos = intento
            propuesta = generar_sql(r.pregunta, historial or [], sql_fallido, error)
            r.grafico, r.titulo = propuesta["grafico"], propuesta["titulo"]
            if not propuesta["sql"]:
                # El modelo dice que no se puede responder (o renuncia tras un error): no es un fallo
                r.sql, error = None, None
                r.texto = propuesta["explicacion"] or "No puedo responder esa pregunta con los datos de TechNova."
                break
            r.sql = propuesta["sql"]
            try:
                r.sql = sqlparse.format(validar(r.sql), reindent=True, keyword_case="upper")
                r.columnas, r.filas = ejecutar_con_permisos(con_limite(r.sql))
                error = None
                break
            except (SQLNoPermitido, psycopg.Error) as e:
                error = e.diag.message_primary if isinstance(e, psycopg.Error) and e.diag.message_primary else str(e)
                sql_fallido = r.sql
                r.sql_fallidos.append({"sql": r.sql, "error": error})
        if error:
            r.error = f"No he conseguido una consulta válida: {error}"
            r.texto = "No he podido responder a esta pregunta. Prueba a formularla de otra manera."
        elif r.filas is not None and resumir:
            try:
                r.texto = llm.generar(SISTEMA_RESUMEN, mensaje_resumen(r)).strip()
            except llm.ErrorLLM:
                r.texto = f"{r.titulo}: {len(r.filas)} filas (no se ha podido generar el resumen)."
    except llm.ErrorLLM as e:
        r.error = str(e)
        r.texto = "El modelo de IA no está disponible ahora mismo."
    r.segundos = time.time() - inicio
    if registrar:
        bd.registrar(r, llm.proveedor(), llm.modelo())
    return r


def ejecutar_con_permisos(sql_texto):
    """Si dbt ha recreado las tablas, el usuario lector pierde los permisos: se renuevan y se repite."""
    try:
        return bd.ejecutar(sql_texto)
    except psycopg.errors.InsufficientPrivilege:
        bd.preparar()
        return bd.ejecutar(sql_texto)
