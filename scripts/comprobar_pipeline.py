"""
comprobar_pipeline.py -> Comprueba que una ejecución completa de TechNova ha dejado todo en su sitio.

Se usa en el CI de GitHub Actions después de reiniciar_todo.py, pero también se puede
lanzar en local para revisar el estado del proyecto:

    python scripts/comprobar_pipeline.py

Termina con código 1 si alguna comprobación falla (y entonces el CI se pone en rojo).
"""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "etl"))

from conexiones import conectar_dw, conectar_oltp  # noqa: E402

# (descripción, base de datos, consulta que devuelve un número, mínimo exigido)
COMPROBACIONES = [
    ("Clientes en la OLTP", "oltp", "SELECT COUNT(*) FROM oltp.cliente", 100),
    ("Pedidos en la OLTP", "oltp", "SELECT COUNT(*) FROM oltp.pedido", 100),
    ("Última ejecución del ETL sin errores", "dw",
     "SELECT COUNT(*) FROM etl.ejecucion WHERE id_ejecucion = (SELECT MAX(id_ejecucion) FROM etl.ejecucion) "
     "AND estado IN ('ok', 'aviso')", 1),
    ("Tipos de cambio cargados", "dw", "SELECT COUNT(*) FROM staging.tipo_cambio", 100),
    ("Tarifas de proveedor cargadas", "dw", "SELECT COUNT(*) FROM staging.proveedor_tarifa", 10),
    ("Fichajes de RRHH cargados desde Excel", "dw", "SELECT COUNT(*) FROM staging.rrhh_fichaje", 100),
    ("Líneas en fct_ventas", "dw", "SELECT COUNT(*) FROM marts.fct_ventas", 100),
    ("Ventas del data warehouse = ventas de la OLTP (céntimo arriba o abajo)", "dw",
     "SELECT CASE WHEN ABS((SELECT SUM(importe_neto) FROM marts.fct_ventas) - {total_oltp}) < 1 THEN 1 ELSE 0 END", 1),
    ("Días en dim_fecha", "dw", "SELECT COUNT(*) FROM marts.dim_fecha", 365 * 3),
    ("Centros con datos de RRHH en diciembre de 2025", "dw",
     "SELECT COUNT(*) FROM marts.rpt_rrhh_centro_mes WHERE mes = '2025-12-01'", 12),
    ("Segmentos de clientes (K-Means)", "dw", "SELECT COUNT(*) FROM ml.segmento_resumen", 4),
    ("Días de previsión de ventas (2 canales)", "dw", "SELECT COUNT(*) FROM ml.prevision_ventas", 2 * 89),
    ("Modelos comparados en el backtest", "dw", "SELECT COUNT(*) FROM ml.metricas_prevision", 8),
]


def main():
    fallos = 0
    with conectar_oltp() as oltp, conectar_dw() as dw:
        # Total de ventas de la OLTP (mismo criterio que fct_ventas: pedidos no cancelados)
        total_oltp = oltp.execute("""
            SELECT COALESCE(SUM(l.cantidad * l.precio_unitario - l.descuento), 0)
            FROM oltp.linea_pedido l JOIN oltp.pedido p USING (id_pedido)
            WHERE p.estado <> 'cancelado'
        """).fetchone()[0]
        for descripcion, base, consulta, minimo in COMPROBACIONES:
            conn = oltp if base == "oltp" else dw
            valor = conn.execute(consulta.format(total_oltp=total_oltp)).fetchone()[0]
            correcto = valor is not None and valor >= minimo
            fallos += not correcto
            print(f"  [{'OK ' if correcto else 'MAL'}] {descripcion}: {valor} (mínimo {minimo})")

    informes = list((RAIZ / "informes" / "2025-12").glob("*.xlsx"))
    correcto = len(informes) == 10
    fallos += not correcto
    print(f"  [{'OK ' if correcto else 'MAL'}] Informes Excel de diciembre de 2025: {len(informes)} (se esperan 10)")

    if fallos:
        sys.exit(f"\n{fallos} comprobaciones han fallado")
    print("\nTodo correcto")


if __name__ == "__main__":
    main()
