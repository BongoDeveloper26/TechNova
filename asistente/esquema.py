"""
esquema.py -> Prepara lo que el LLM necesita saber de la base de datos (el "contexto").

Junta tres fuentes:
  1. catalogo.yml: qué significa cada tabla, cómo se calculan las métricas y qué errores evitar
  2. La base de datos: las columnas y tipos REALES de cada tabla (si cambia el modelo de dbt,
     el asistente se entera solo)
  3. Los valores de las columnas de texto con pocos valores distintos (canal, categoría,
     tienda...). Sin esto, el modelo escribiría WHERE canal = 'online' en vez de 'web'.
"""
from functools import lru_cache
from pathlib import Path

import yaml
from psycopg import sql as psql

from bd import conectar_dw, tablas_visibles

CATALOGO = Path(__file__).with_name("catalogo.yml")
MAX_VALORES = 20          # columnas de texto con hasta 20 valores distintos: se listan todos
TIPOS_TEXTO = {"text", "character varying", "character"}


def cargar_catalogo() -> dict:
    return yaml.safe_load(CATALOGO.read_text(encoding="utf-8"))


def valores_categoricos(conn, tabla, columnas) -> dict:
    """{columna: [valores]} de las columnas de texto con pocos valores distintos."""
    resultado = {}
    esquema, nombre = tabla.split(".")
    for columna, tipo in columnas:
        if tipo not in TIPOS_TEXTO or columna.startswith("id_") or columna in ("sku", "cif"):
            continue
        valores = conn.execute(psql.SQL(
            "SELECT DISTINCT {c} FROM {e}.{t} WHERE {c} IS NOT NULL LIMIT {n}"
        ).format(c=psql.Identifier(columna), e=psql.Identifier(esquema), t=psql.Identifier(nombre),
                 n=psql.Literal(MAX_VALORES + 1))).fetchall()
        if 0 < len(valores) <= MAX_VALORES:
            resultado[columna] = sorted(v[0] for v in valores)
    return resultado


@lru_cache(maxsize=1)
def contexto() -> str:
    """El texto que se le da al LLM para que conozca la base de datos (se calcula una vez)."""
    catalogo = cargar_catalogo()
    lineas = [catalogo["contexto"].strip(), "", "TABLAS DISPONIBLES (PostgreSQL):"]
    with conectar_dw() as conn:
        tablas = tablas_visibles(conn)
        for tabla, descripcion in catalogo["tablas"].items():
            if tabla not in tablas:
                continue
            lineas.append(f"\n{tabla} -- {' '.join(descripcion.split())}")
            lineas.append("  columnas: " + ", ".join(f"{c} ({t})" for c, t in tablas[tabla]))
            for columna, valores in valores_categoricos(conn, tabla, tablas[tabla]).items():
                lineas.append(f"  valores de {columna}: " + ", ".join(f"'{v}'" for v in valores))
    lineas += ["", "RELACIONES:"] + [f"- {r}" for r in catalogo["relaciones"]]
    lineas += ["", "MÉTRICAS DE NEGOCIO (úsalas siempre así):"]
    lineas += [f"- {nombre}: {definicion}" for nombre, definicion in catalogo["metricas"].items()]
    lineas += ["", "REGLAS:"] + [f"- {r}" for r in catalogo["reglas"]]
    return "\n".join(lineas)
