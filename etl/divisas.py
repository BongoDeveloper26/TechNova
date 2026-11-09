"""
divisas.py -> ETL de tipos de cambio desde una API REST.

  E: pide a la API de Frankfurter los tipos de cambio oficiales del BCE
     desde el último día cargado hasta la fecha de proceso (carga incremental).
  T: valida la respuesta y rellena fines de semana y festivos con el último
     valor conocido (el BCE no publica esos días, pero nosotros compramos igual).
  L: UPSERT en staging.tipo_cambio.
"""
import time
from datetime import timedelta

import pandas as pd
import requests

from configuracion import (API_DIVISAS_PROVEEDOR, API_DIVISAS_URL, API_REINTENTOS,
                           API_TIMEOUT_SEG, DIVISAS_DESDE, MONEDAS)
from registro import log


# ---------------------------------------------------------------------
# EXTRACT
# ---------------------------------------------------------------------

def pedir_a_la_api(desde, hasta):
    """GET con reintentos: si la API falla, espera cada vez más antes de volver a probar."""
    parametros = {
        "from": desde.isoformat(), "to": hasta.isoformat(),
        "base": "EUR", "quotes": ",".join(MONEDAS), "providers": API_DIVISAS_PROVEEDOR,
    }
    for intento in range(1, API_REINTENTOS + 1):
        try:
            respuesta = requests.get(API_DIVISAS_URL, params=parametros, timeout=API_TIMEOUT_SEG)
            if respuesta.status_code == 503 and intento < API_REINTENTOS:
                espera = int(respuesta.headers.get("Retry-After", 2 ** intento))
                log.warning(f"   API saturada (503). Reintento {intento} en {espera} s")
                time.sleep(espera)
                continue
            respuesta.raise_for_status()
            return respuesta.json()
        except requests.ConnectionError as error:
            if intento == API_REINTENTOS:
                raise
            log.warning(f"   Sin conexión con la API ({error}). Reintento {intento} en {2 ** intento} s")
            time.sleep(2 ** intento)
    raise RuntimeError("La API de divisas no ha respondido")


# ---------------------------------------------------------------------
# TRANSFORM
# ---------------------------------------------------------------------

def transformar(datos, desde, hasta):
    """
    La API devuelve una lista así:
        [{"date": "2025-01-02", "base": "EUR", "quote": "USD", "rate": 1.0321}, ...]
    Devolvemos una fila por (día del calendario, moneda), sin huecos.
    """
    if not isinstance(datos, list):
        raise ValueError(f"Respuesta inesperada de la API: {str(datos)[:200]}")

    df = pd.DataFrame(datos)
    if df.empty:
        raise ValueError("La API no ha devuelto ningún tipo de cambio")
    columnas_esperadas = {"date", "base", "quote", "rate"}
    if not columnas_esperadas.issubset(df.columns):
        raise ValueError(f"Faltan columnas en la respuesta: {columnas_esperadas - set(df.columns)}")

    df = df[(df["base"] == "EUR") & (df["quote"].isin(MONEDAS))]
    df["fecha"] = pd.to_datetime(df["date"]).dt.date
    df["tasa"] = pd.to_numeric(df["rate"], errors="coerce")
    malos = df["tasa"].isna() | (df["tasa"] <= 0)
    if malos.any():
        raise ValueError(f"{malos.sum()} tipos de cambio no válidos en la respuesta")

    # Tabla ancha (una columna por moneda) con TODOS los días del calendario
    ancha = df.pivot_table(index="fecha", columns="quote", values="tasa")
    calendario = pd.date_range(min(ancha.index), hasta).date
    ancha = ancha.reindex(calendario)
    interpolado = ancha.isna()
    ancha = ancha.ffill()  # fin de semana -> se repite el viernes

    filas = []
    for dia in calendario:
        if dia < desde:
            continue
        for moneda in MONEDAS:
            tasa = ancha.at[dia, moneda] if moneda in ancha.columns else None
            if pd.isna(tasa):
                continue  # no hay ningún valor previo que arrastrar
            filas.append((dia, moneda, round(float(tasa), 6), bool(interpolado.at[dia, moneda]),
                          API_DIVISAS_PROVEEDOR))
        filas.append((dia, "EUR", 1.0, False, "fijo"))  # el euro siempre vale 1 €
    return filas


# ---------------------------------------------------------------------
# LOAD
# ---------------------------------------------------------------------

def cargar(conn_dw, filas):
    with conn_dw.cursor() as cur:
        cur.executemany(
            """INSERT INTO staging.tipo_cambio (fecha, moneda, tasa, es_interpolado, fuente)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (fecha, moneda) DO UPDATE
               SET tasa = EXCLUDED.tasa, es_interpolado = EXCLUDED.es_interpolado,
                   fuente = EXCLUDED.fuente, cargado_en = now()""",
            filas,
        )


def ejecutar(conn_dw, fecha_proceso, resultado):
    ultima = conn_dw.execute(
        "SELECT MAX(fecha) FROM staging.tipo_cambio WHERE NOT es_interpolado AND moneda <> 'EUR'"
    ).fetchone()[0]
    # Volvemos a pedir desde el último día REAL publicado: así los días que rellenamos
    # (interpolados) se sustituyen por el valor oficial si el BCE lo publica después
    desde = ultima if ultima else DIVISAS_DESDE
    if desde > fecha_proceso:
        log.info("   Tipos de cambio ya al día")
        return

    # Pedimos una semana extra hacia atrás: si "desde" cae en sábado,
    # necesitamos el viernes anterior para rellenarlo
    log.info(f"   Pidiendo tipos de cambio del {desde} al {fecha_proceso}")
    datos = pedir_a_la_api(desde - timedelta(days=7), fecha_proceso)
    resultado.leidas = len(datos)

    filas = transformar(datos, desde, fecha_proceso)
    cargar(conn_dw, filas)
    resultado.cargadas = len(filas)
    interpolados = sum(1 for f in filas if f[3])
    log.info(f"   {len(filas)} filas ({interpolados} interpoladas por fin de semana o festivo)")