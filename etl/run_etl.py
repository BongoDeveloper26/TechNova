"""
run_etl.py -> Lanza el ETL.

Se puede usar de dos formas:

1) A mano, desde la terminal (todo seguido):
    python etl/run_etl.py                          # fecha de proceso = hoy
    python etl/run_etl.py --fecha 2025-12-31       # procesar un día concreto
    python etl/run_etl.py --pasos divisas,calidad  # solo algunos pasos

2) Desde Airflow, paso a paso (cada paso en una tarea distinta):
    id = abrir_ejecucion(fecha)
    ejecutar_paso(id, "oltp")      ...
    cerrar_ejecucion(id)

Orden de los pasos:
    oltp ───┬──────────────> rrhh ──────┐
            ├──> proveedores ───────────┼──> calidad ──> dbt ──> informes
    divisas ┘                           │
    (proveedores necesita el catálogo y los tipos de cambio; rrhh necesita los empleados;
     dbt solo debe ejecutarse si la calidad está bien;
     informes genera los Excel mensuales, solo el último día del mes)

Código de salida: 0 si todo va bien o con avisos, 1 si hay errores.
"""
import argparse
import sys
from datetime import date

from conexiones import conectar_dw, conectar_oltp, preparar_dw
from registro import Ejecucion, log

PASOS = ["oltp", "divisas", "proveedores", "rrhh", "calidad", "dbt", "informes"]

NOMBRES = {
    "oltp": "Extraer OLTP -> staging",
    "divisas": "API tipos de cambio -> staging",
    "proveedores": "CSV proveedores -> staging",
    "rrhh": "Excel RRHH -> staging",
    "calidad": "Controles de calidad",
    "dbt": "dbt build -> data warehouse",
    "informes": "Informes mensuales en Excel",
}


class PasoFallido(RuntimeError):
    """Se lanza cuando un paso termina en error (para que Airflow lo marque en rojo y reintente)."""


def abrir_ejecucion(fecha_proceso: date, parametros=None) -> int:
    preparar_dw()
    with conectar_dw() as conn_dw:
        return Ejecucion.nueva(conn_dw, fecha_proceso, parametros or {}).id


def ejecutar_paso(id_ejecucion: int, paso: str, lanzar_si_falla: bool = True) -> str:
    # Los módulos se importan aquí dentro: cada paso solo carga lo que necesita
    import calidad
    import divisas
    import excel_rrhh
    import extraer_oltp
    import informes_excel
    import proveedores
    import transformar_dbt

    with conectar_oltp() as conn_oltp, conectar_dw() as conn_dw:
        ejecucion = Ejecucion(conn_dw, id_ejecucion)
        fecha = ejecucion.fecha_proceso
        with ejecucion.paso(NOMBRES[paso]) as r:
            if paso == "oltp":
                extraer_oltp.ejecutar(conn_oltp, conn_dw, r)
            elif paso == "divisas":
                divisas.ejecutar(conn_dw, fecha, r)
            elif paso == "proveedores":
                proveedores.ejecutar(conn_dw, ejecucion.id, fecha, r)
            elif paso == "rrhh":
                excel_rrhh.ejecutar(conn_dw, ejecucion.id, fecha, r)
            elif paso == "calidad":
                calidad.ejecutar(conn_oltp, conn_dw, ejecucion.id, fecha, r)
            elif paso == "dbt":
                transformar_dbt.ejecutar(r)
            elif paso == "informes":
                informes_excel.ejecutar(fecha, r)
            else:
                raise ValueError(f"Paso desconocido: {paso}")

    if r.estado == "error" and lanzar_si_falla:
        raise PasoFallido(f"El paso '{paso}' ha fallado: {' | '.join(r.detalle)}")
    return r.estado


def cerrar_ejecucion(id_ejecucion: int) -> str:
    with conectar_dw() as conn_dw:
        return Ejecucion(conn_dw, id_ejecucion).cerrar()


def ejecutar_etl(fecha_proceso: date, pasos=PASOS) -> str:
    """
    Todo seguido. Si un paso falla, se apunta y se sigue con los demás,
    salvo dbt: si la calidad ha fallado, no se transforman datos incorrectos.
    """
    id_ejecucion = abrir_ejecucion(fecha_proceso, {"pasos": pasos, "origen": "terminal"})
    estados = {}
    for paso in pasos:
        if paso == "dbt" and estados.get("calidad") == "error":
            log.error("-> dbt NO se ejecuta porque los controles de calidad han fallado")
            continue
        if paso == "informes" and estados.get("dbt") == "error":
            log.error("-> Los informes NO se generan porque dbt ha fallado")
            continue
        estados[paso] = ejecutar_paso(id_ejecucion, paso, lanzar_si_falla=False)
    return cerrar_ejecucion(id_ejecucion)


def main():
    parser = argparse.ArgumentParser(description="ETL de TechNova")
    parser.add_argument("--fecha", type=date.fromisoformat, default=date.today(),
                        help="Fecha de proceso AAAA-MM-DD (por defecto, hoy)")
    parser.add_argument("--pasos", default=",".join(PASOS),
                        help=f"Pasos separados por comas: {','.join(PASOS)}")
    args = parser.parse_args()

    pasos = [p.strip() for p in args.pasos.split(",")]
    desconocidos = set(pasos) - set(PASOS)
    if desconocidos:
        parser.error(f"Pasos desconocidos: {desconocidos}")

    estado = ejecutar_etl(args.fecha, pasos)
    if estado == "error":
        log.error("El ETL ha terminado con errores. Revisa etl.paso y etl.control_calidad")
        sys.exit(1)


if __name__ == "__main__":
    main()