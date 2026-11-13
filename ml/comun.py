"""
comun.py -> Piezas compartidas por los modelos de Machine Learning.

  - Conexión al data warehouse (se reutiliza la del ETL)
  - Leer una consulta SQL como DataFrame de pandas
  - Crear el esquema ml y registrar cada entrenamiento en ml.ejecucion
  - Carpetas donde se guardan los modelos entrenados y los gráficos
"""
import json
import sys
import time
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "etl"))           # para reutilizar conexiones.py del ETL

from conexiones import conectar_dw  # noqa: E402,F401  (los modelos la importan desde aquí)

CARPETA_MODELOS = RAIZ / "models"              # modelos entrenados (.joblib), no se suben a Git
CARPETA_GRAFICOS = RAIZ / "docs" / "ml"        # gráficos para el README
FICHERO_ESQUEMA_ML = RAIZ / "sql" / "dw" / "02_ml_schema.sql"
SEMILLA = 42                                   # misma semilla = mismos resultados en cada ejecución


def leer(conn, sql: str, params=None, fechas=()) -> pd.DataFrame:
    """Ejecuta una consulta y devuelve un DataFrame (los NUMERIC de Postgres pasan a float)."""
    cursor = conn.execute(sql, params)
    columnas = [c.name for c in cursor.description]
    df = pd.DataFrame(cursor.fetchall(), columns=columnas)
    for col in df.columns:
        if col in fechas:
            df[col] = pd.to_datetime(df[col])
        elif df[col].map(lambda v: isinstance(v, Decimal)).any():
            df[col] = df[col].astype(float)
    return df


def preparar_esquema(conn):
    conn.execute(FICHERO_ESQUEMA_ML.read_text(encoding="utf-8"))


def a_python(valor):
    """numpy -> tipos de Python (para guardar en JSON o en la base de datos)."""
    if hasattr(valor, "item"):
        return valor.item()
    return valor


@contextmanager
def registrar_ejecucion(conn, modelo: str, parametros: dict):
    """
    Abre una fila en ml.ejecucion y al terminar guarda la duración y las métricas.
    Uso:
        with registrar_ejecucion(conn, "segmentacion_clientes", {...}) as ejecucion:
            ...
            ejecucion["metricas"] = {...}
            ejecucion["datos_hasta"] = fecha
    """
    inicio = time.time()
    id_ejecucion = conn.execute(
        "INSERT INTO ml.ejecucion (modelo, parametros) VALUES (%s, %s) RETURNING id_ejecucion",
        (modelo, json.dumps(parametros, default=a_python)),
    ).fetchone()[0]
    ejecucion = {"id": id_ejecucion, "metricas": {}, "datos_hasta": None}
    yield ejecucion
    conn.execute(
        "UPDATE ml.ejecucion SET duracion_seg = %s, metricas = %s, datos_hasta = %s WHERE id_ejecucion = %s",
        (round(time.time() - inicio, 1), json.dumps(ejecucion["metricas"], default=a_python),
         ejecucion["datos_hasta"], id_ejecucion),
    )


def preparar_graficos():
    """matplotlib sin ventana (en Airflow no hay pantalla) y con un estilo limpio."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "figure.dpi": 110, "savefig.dpi": 130, "savefig.bbox": "tight",
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.titleweight": "bold", "axes.titlesize": 12, "font.size": 9,
        "axes.grid": True, "grid.alpha": 0.25,
    })
    CARPETA_GRAFICOS.mkdir(parents=True, exist_ok=True)
    return plt


COLORES = ["#2F5597", "#ED7D31", "#A5A5A5", "#FFC000", "#5B9BD5", "#70AD47", "#264478", "#9E480E"]