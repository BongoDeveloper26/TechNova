"""
DAG technova_etl -> Ejecuta el ETL de TechNova todas las noches.

Un DAG (Directed Acyclic Graph) es la lista de tareas y el ORDEN en que se ejecutan:

    fecha_proceso ─> simular_ficheros ─> abrir_ejecucion ─┬─> extraer_oltp ─┬──────────────> rrhh ──┐
                                                           │                 ├─> proveedores ─────────┼─> calidad ─> dbt ─> informes ─> cerrar_ejecucion
                                                           └─> divisas ──────┘                        │

  - extraer_oltp y divisas no dependen la una de la otra: Airflow las lanza A LA VEZ.
  - proveedores espera a las dos (necesita el catálogo y los tipos de cambio).
  - rrhh (los Excel de Recursos Humanos) solo necesita los empleados de la OLTP.
  - dbt solo se ejecuta si calidad ha ido bien: no se transforman datos incorrectos.
  - informes genera los Excel mensuales (solo el último día del mes; los demás días no hace nada).
  - cerrar_ejecucion se ejecuta SIEMPRE (trigger_rule=ALL_DONE), aunque algo falle,
    para que la ejecución quede cerrada en etl.ejecucion con su estado real.

Cada noche a las 03:00 procesa el día ANTERIOR (que ya está completo).
Se puede lanzar a mano desde la web indicando una fecha concreta.

Las importaciones del ETL están DENTRO de las tareas: Airflow lee este fichero
cada pocos segundos para detectar cambios, y así esa lectura es instantánea.
"""
from datetime import date, datetime, timedelta

from airflow.sdk import Param, dag, get_current_context, task
from airflow.task.trigger_rule import TriggerRule

ARGUMENTOS_POR_DEFECTO = {
    "owner": "technova-data",
    "retries": 2,                         # si una tarea falla, se reintenta 2 veces...
    "retry_delay": timedelta(minutes=2),  # ...esperando 2 minutos entre intentos
}


@dag(
    dag_id="technova_etl",
    description="ELT diario: OLTP + API de divisas + CSV de proveedores -> staging -> dbt -> marts",
    schedule="0 3 * * *",                 # cron: minuto 0, hora 3, todos los días
    start_date=datetime(2025, 12, 1),
    catchup=False,                        # no ejecutar automáticamente los días pasados
    max_active_runs=1,                    # nunca dos ejecuciones a la vez
    default_args=ARGUMENTOS_POR_DEFECTO,
    tags=["technova", "etl", "dbt"],
    doc_md=__doc__,
    params={
        "fecha": Param(
            None, type=["null", "string"], format="date",
            description="Fecha a procesar (AAAA-MM-DD). Vacío = el día anterior a la ejecución",
        ),
        "simular_proveedores": Param(
            True, type="boolean",
            description="Generar los CSV de proveedores (y los Excel de RRHH si es fin de mes). En un caso real llegarían solos",
        ),
    },
)
def technova_etl():

    @task
    def fecha_proceso() -> str:
        """Decide qué día se procesa."""
        contexto = get_current_context()
        if contexto["params"].get("fecha"):
            return contexto["params"]["fecha"]
        # En una ejecución programada, logical_date es el momento en que tocaba ejecutar.
        # En una lanzada a mano puede no existir, y usamos cuándo se lanzó (run_after).
        momento = contexto.get("logical_date") or contexto["dag_run"].run_after
        return (momento - timedelta(days=1)).date().isoformat()

    @task
    def simular_ficheros(fecha: str) -> int:
        """
        Hace de 'mundo exterior':
          - cada día llegan los CSV de los proveedores
          - el último día del mes llegan además los Excel de RRHH de ese mes
        """
        if not get_current_context()["params"].get("simular_proveedores", True):
            return 0
        from simular_proveedores import simular
        from simular_rrhh import simular_mes_si_falta
        dia = date.fromisoformat(fecha)
        total = simular(dia, dia)
        if (dia + timedelta(days=1)).day == 1:
            total += simular_mes_si_falta(dia)
        return total

    @task
    def abrir_ejecucion(fecha: str) -> int:
        from run_etl import abrir_ejecucion as abrir
        return abrir(date.fromisoformat(fecha), {"origen": "airflow",
                                                 "run_id": get_current_context()["run_id"]})

    @task
    def extraer_oltp(id_ejecucion: int) -> str:
        from run_etl import ejecutar_paso
        return ejecutar_paso(id_ejecucion, "oltp")

    @task
    def divisas(id_ejecucion: int) -> str:
        from run_etl import ejecutar_paso
        return ejecutar_paso(id_ejecucion, "divisas")

    @task
    def proveedores(id_ejecucion: int) -> str:
        from run_etl import ejecutar_paso
        return ejecutar_paso(id_ejecucion, "proveedores")

    @task
    def rrhh(id_ejecucion: int) -> str:
        from run_etl import ejecutar_paso
        return ejecutar_paso(id_ejecucion, "rrhh")

    @task(retries=0)  # si los datos están mal, reintentar no los arregla
    def calidad(id_ejecucion: int) -> str:
        from run_etl import ejecutar_paso
        return ejecutar_paso(id_ejecucion, "calidad")

    @task(retries=1)
    def transformar_dbt(id_ejecucion: int) -> str:
        """dbt build: staging -> esquema en estrella (marts), con sus tests."""
        from run_etl import ejecutar_paso
        return ejecutar_paso(id_ejecucion, "dbt")

    @task
    def informes(id_ejecucion: int) -> str:
        """El último día del mes: informes Excel de cada tienda y de RRHH en informes/<AAAA-MM>/."""
        from run_etl import ejecutar_paso
        return ejecutar_paso(id_ejecucion, "informes")

    @task(trigger_rule=TriggerRule.ALL_DONE, retries=0)
    def cerrar_ejecucion(id_ejecucion: int) -> str:
        from run_etl import cerrar_ejecucion as cerrar
        estado = cerrar(id_ejecucion)
        if estado == "error":
            # Si no fallamos aquí, Airflow pondría la ejecución en verde
            # porque esta (la última tarea) ha terminado bien
            raise RuntimeError(f"La ejecución {id_ejecucion} ha terminado con errores")
        return estado

    # ----- Orden de las tareas -----
    fecha = fecha_proceso()
    ficheros = simular_ficheros(fecha)
    id_ejecucion = abrir_ejecucion(fecha)
    ficheros >> id_ejecucion

    oltp = extraer_oltp(id_ejecucion)
    tipos = divisas(id_ejecucion)
    tarifas = proveedores(id_ejecucion)
    excel_rrhh = rrhh(id_ejecucion)
    controles = calidad(id_ejecucion)

    modelo = transformar_dbt(id_ejecucion)

    [oltp, tipos] >> tarifas
    oltp >> excel_rrhh
    excel_informes = informes(id_ejecucion)
    [tarifas, excel_rrhh] >> controles >> modelo >> excel_informes >> cerrar_ejecucion(id_ejecucion)


technova_etl()