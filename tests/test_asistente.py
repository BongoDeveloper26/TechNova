"""
Tests del asistente de preguntas en lenguaje natural, sin base de datos ni IA:
la seguridad del SQL, la lectura del JSON del modelo y el flujo con autocorrección
(el LLM y la base de datos se sustituyen por versiones falsas).
"""
import psycopg
import pytest

import asistente
import llm
from evaluar import coinciden
from seguridad import SQLNoPermitido, con_limite, validar


# ---------------------------------------------------------------------
# Seguridad
# ---------------------------------------------------------------------

@pytest.mark.parametrize("sql", [
    "SELECT 1",
    "select canal, sum(importe_neto) from marts.fct_ventas group by canal;",
    "WITH t AS (SELECT * FROM ml.segmento_resumen) SELECT * FROM t",
    "SELECT * FROM marts.dim_producto WHERE producto = 'Mesa; DROP TABLE x'",   # ';' y DROP dentro de un texto
    "-- comentario con delete\nSELECT dia FROM marts.fct_ventas",
])
def test_consultas_de_lectura_permitidas(sql):
    limpio = validar(sql)
    assert limpio and not limpio.endswith(";")


@pytest.mark.parametrize("sql, motivo", [
    ("", "vacía"),
    ("DELETE FROM marts.fct_ventas", "lectura"),
    ("SELECT 1; DROP TABLE marts.fct_ventas", "una sentencia"),
    ("WITH x AS (DELETE FROM marts.fct_ventas RETURNING *) SELECT * FROM x", "DELETE"),
    ("SELECT * INTO marts.copia FROM marts.fct_ventas", "INTO"),
    ("SELECT pg_sleep(30)", "PG_SLEEP"),
    ("SELECT * FROM staging.oltp_cliente", "staging"),
    ("SELECT * FROM etl.ejecucion", "etl"),
    ("SELECT usename FROM pg_catalog.pg_user", "pg_catalog"),
    ("SELECT set_config('statement_timeout', '0', false)", "SET_CONFIG"),
])
def test_consultas_peligrosas_bloqueadas(sql, motivo):
    with pytest.raises(SQLNoPermitido, match=motivo):
        validar(sql)


def test_limite_de_filas():
    assert con_limite("SELECT 1", 10).endswith("LIMIT 10")


# ---------------------------------------------------------------------
# Respuestas del modelo
# ---------------------------------------------------------------------

@pytest.mark.parametrize("texto", [
    '{"sql": "SELECT 1"}',
    '```json\n{"sql": "SELECT 1"}\n```',
    'Aquí tienes:\n{"sql": "SELECT 1"}\nEspero que ayude',
])
def test_extraer_json_aunque_venga_envuelto(texto):
    assert llm.extraer_json(texto) == {"sql": "SELECT 1"}


def test_extraer_json_invalido():
    with pytest.raises(llm.ErrorLLM):
        llm.extraer_json("no sé")


def test_proveedor_no_valido(monkeypatch):
    monkeypatch.setenv("LLM_PROVEEDOR", "chatbot")
    with pytest.raises(llm.ErrorLLM, match="no es válido"):
        llm.proveedor()


# ---------------------------------------------------------------------
# Flujo completo con un LLM y una base de datos falsos
# ---------------------------------------------------------------------

@pytest.fixture
def falsos(monkeypatch):
    """El LLM devuelve las respuestas de la lista en orden; la base de datos solo conoce una columna."""
    respuestas, llamadas = [], []

    def generar(sistema, mensaje, json_salida=False):
        llamadas.append(mensaje)
        return respuestas.pop(0)

    def ejecutar(sql):
        if "columna_mala" in sql:
            raise psycopg.errors.UndefinedColumn('column "columna_mala" does not exist')
        return ["canal", "facturacion"], [("web", 100.0), ("tienda", 50.0)]

    monkeypatch.setattr(asistente, "contexto", lambda: "CONTEXTO")
    monkeypatch.setattr(asistente.llm, "generar", generar)
    monkeypatch.setattr(asistente.bd, "ejecutar", ejecutar)
    return respuestas, llamadas


def test_pregunta_respondida(falsos):
    respuestas, _ = falsos
    respuestas += ['{"sql": "SELECT canal, 1 FROM marts.fct_ventas", "grafico": "tarta", "titulo": "Por canal"}',
                   "La web factura el doble que las tiendas."]
    r = asistente.preguntar("¿Cuánto vende cada canal?", registrar=False)
    assert r.error is None and r.intentos == 1 and r.grafico == "tarta"
    assert r.filas == [("web", 100.0), ("tienda", 50.0)]
    assert r.texto == "La web factura el doble que las tiendas."


def test_autocorreccion_tras_un_error_de_sql(falsos):
    respuestas, llamadas = falsos
    respuestas += ['{"sql": "SELECT columna_mala FROM marts.fct_ventas"}',
                   '{"sql": "SELECT canal FROM marts.fct_ventas", "grafico": "barras"}',
                   "Resumen."]
    r = asistente.preguntar("¿Ventas por canal?", registrar=False)
    assert r.error is None and r.intentos == 2
    assert "columna_mala" in r.sql_fallidos[0]["sql"]
    assert "columna_mala" in llamadas[1] and "ha fallado" in llamadas[1]   # el error vuelve al modelo


def test_sql_peligroso_nunca_llega_a_la_base_de_datos(falsos):
    respuestas, _ = falsos
    respuestas += ['{"sql": "DROP TABLE marts.fct_ventas"}', '{"sql": "DROP TABLE marts.fct_ventas"}']
    r = asistente.preguntar("Borra la tabla de ventas", registrar=False)
    assert r.error and r.filas is None


def test_pregunta_sin_respuesta_posible(falsos):
    respuestas, _ = falsos
    respuestas += ['{"sql": null, "explicacion": "TechNova no tiene centros en Marte."}']
    r = asistente.preguntar("¿Cuántas tiendas hay en Marte?", registrar=False)
    assert r.error is None and r.sql is None and "Marte" in r.texto


def test_preguntas_de_seguimiento_llevan_la_conversacion(falsos):
    respuestas, llamadas = falsos
    respuestas += ['{"sql": "SELECT 1"}', "Resumen."]
    anterior = asistente.Respuesta(pregunta="¿Qué tienda vendió más en 2025?", sql="SELECT 2025")
    asistente.preguntar("¿y en 2024?", historial=[anterior], registrar=False)
    assert "¿Qué tienda vendió más en 2025?" in llamadas[0] and "SELECT 2025" in llamadas[0]


# ---------------------------------------------------------------------
# Evaluación
# ---------------------------------------------------------------------

def test_comparacion_de_resultados_tolerante():
    assert coinciden([("web", 0.0681)], [("web", 6.81, 123)])          # porcentaje y columna de más
    assert coinciden([("x", 1), ("y", 2)], [("y", 2.0), ("x", 1)])      # otro orden
    assert not coinciden([("a", 1)], [("b", 1)])
    assert coinciden([("a", 1)], [("a", 1), ("b", 2)])                 # "¿cuál es el que más?": vale el ranking
    assert not coinciden([("b", 2)], [("a", 1), ("b", 2)])              # ...si el primero es el correcto
    assert not coinciden([("a", 1), ("b", 2)], [("a", 1)])