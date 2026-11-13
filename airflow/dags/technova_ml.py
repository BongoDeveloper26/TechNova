"""
DAG technova_ml -> Reentrena los modelos de Machine Learning una vez al mes.

    comprobar_datos ─┬─> segmentar_clientes ──┐
                     └─> prever_ventas ───────┴─> resumen

  - Se ejecuta el día 1 de cada mes a las 05:00, cuando el ETL de las 03:00
    ya ha cargado el último día del mes anterior.
  - comprobar_datos para el DAG si el data warehouse no está al día: entrenar
    con datos incompletos daría una previsión equivocada.
  - Los dos modelos son independientes: Airflow los entrena A LA VEZ.
  - Cada entrenamiento queda registrado en ml.ejecucion con sus parámetros y métricas.

¿Por qué un DAG aparte y no una tarea más del ETL diario? Porque tienen ritmos
distintos: los datos cambian cada día, pero reentrenar cada día no aporta nada
y gasta recursos. Separarlos también permite reentrenar a mano sin tocar el ETL.
"""
from datetime import date, datetime, timedelta

from airflow.sdk import dag, get_current_context, task

ARGUMENTOS_POR_DEFECTO = {
    "owner": "technova-data",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


@dag(
    dag_id="technova_ml",
    description="Reentrenamiento mensual: segmentación de clientes (K-Means) y previsión de ventas",
    schedule="0 5 1 * *",            # cron: a las 05:00 del día 1 de cada mes
    start_date=datetime(2025, 12, 1),
    catchup=False,
    max_active_runs=1,
    default_args=ARGUMENTOS_POR_DEFECTO,
    tags=["technova", "ml"],
    doc_md=__doc__,
)
def technova_ml():

    @task(retries=0)
    def comprobar_datos() -> str:
        """El último día con ventas en el data warehouse debe ser, como pronto, anteayer."""
        from comun import conectar_dw
        with conectar_dw() as conn:
            ultimo = conn.execute("SELECT MAX(dia) FROM marts.fct_ventas").fetchone()[0]
        contexto = get_current_context()
        momento = contexto.get("logical_date") or contexto["dag_run"].run_after
        limite = momento.date() - timedelta(days=2)
        # Los datos de TechNova son simulados y terminan el 31/12/2025: se acepta también ese caso
        if ultimo is None or (ultimo < limite and ultimo < date(2025, 12, 31)):
            raise RuntimeError(f"El data warehouse no está al día (último día con ventas: {ultimo}). "
                               "Revisa el DAG technova_etl antes de reentrenar.")
        return ultimo.isoformat()

    @task
    def segmentar_clientes(_datos_hasta: str) -> dict:
        from segmentacion_clientes import ejecutar
        return ejecutar(log=print)

    @task
    def prever_ventas(_datos_hasta: str) -> dict:
        from prevision_ventas import ejecutar
        return ejecutar(log=print)

    @task
    def resumen(segmentacion: dict, prevision: dict) -> str:
        texto = (f"{segmentacion['clientes']:,} clientes en {segmentacion['k']} segmentos "
                 f"(silueta {segmentacion['silueta']}). Previsión 3 meses: "
                 + ", ".join(f"{c} {v:,.0f} €" for c, v in prevision["prevision_total"].items()))
        print(texto)
        return texto

    datos_hasta = comprobar_datos()
    resumen(segmentar_clientes(datos_hasta), prever_ventas(datos_hasta))


technova_ml()