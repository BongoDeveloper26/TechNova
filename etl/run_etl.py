"""
run_etl.py -> Lanza el ETL completo.

Uso (desde la raíz del proyecto):
    python etl/run_etl.py                          # fecha de proceso = hoy
    python etl/run_etl.py --fecha 2025-12-31       # procesar un día concreto
    python etl/run_etl.py --pasos divisas,calidad  # solo algunos pasos

Orden de los pasos (cada uno necesita el anterior):
    oltp -> divisas -> proveedores -> calidad
           (los proveedores necesitan el catálogo y los tipos de cambio)

Código de salida: 0 si todo va bien o con avisos, 1 si hay errores
(así Airflow, o cualquier otro orquestador, sabe que algo ha fallado).
"""
import argparse
import sys
from datetime import date

import calidad
import divisas
import extraer_oltp
import proveedores
from conexiones import conectar_dw, conectar_oltp, preparar_dw
from registro import Ejecucion, log

PASOS = ["oltp", "divisas", "proveedores", "calidad"]


def ejecutar_etl(fecha_proceso: date, pasos=PASOS) -> str:
    preparar_dw()
    with conectar_oltp() as conn_oltp, conectar_dw() as conn_dw:
        ejecucion = Ejecucion(conn_dw, fecha_proceso, {"pasos": pasos})

        if "oltp" in pasos:
            with ejecucion.paso("Extraer OLTP -> staging") as r:
                extraer_oltp.ejecutar(conn_oltp, conn_dw, r)
        if "divisas" in pasos:
            with ejecucion.paso("API tipos de cambio -> staging") as r:
                divisas.ejecutar(conn_dw, fecha_proceso, r)
        if "proveedores" in pasos:
            with ejecucion.paso("CSV proveedores -> staging") as r:
                proveedores.ejecutar(conn_dw, ejecucion.id, fecha_proceso, r)
        if "calidad" in pasos:
            with ejecucion.paso("Controles de calidad") as r:
                calidad.ejecutar(conn_oltp, conn_dw, ejecucion.id, fecha_proceso, r)

        ejecucion.cerrar()
        return ejecucion.estado


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