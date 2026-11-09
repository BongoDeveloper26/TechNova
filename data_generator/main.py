"""
main.py -> Genera TODA la base de datos de TechNova en el orden correcto.

Uso:
    python data_generator/main.py
"""
import time

import seed_entidades
from db import get_connection
import seed_inventario
import seed_maestros
import seed_postventa
import seed_ventas

PASOS = [
    ("1/5 Datos maestros", seed_maestros),
    ("2/5 Productos, clientes y empleados", seed_entidades),
    ("3/5 Ventas", seed_ventas),
    ("4/5 Devoluciones y garantías", seed_postventa),
    ("5/5 Compras a proveedores y stock", seed_inventario),
]


def finalizar():
    """Tareas de mantenimiento después de una carga masiva."""
    print(f"\n{'=' * 55}\n▶ Mantenimiento\n{'=' * 55}")
    # autocommit: VACUUM no puede ejecutarse dentro de una transacción
    with get_connection() as conn:
        conn.autocommit = True
        # ANALYZE actualiza las estadísticas que usa el planificador de consultas
        # para decidir si usar un índice o no. Tras cargar miles de filas, es obligatorio.
        conn.execute("VACUUM ANALYZE")
        print("   ✅ VACUUM ANALYZE")

        # Las vistas materializadas guardan datos: hay que refrescarlas
        existe = conn.execute("SELECT to_regclass('reporting.mv_clientes_rfm')").fetchone()[0]
        if existe:
            conn.execute("REFRESH MATERIALIZED VIEW reporting.mv_clientes_rfm")
            print("   ✅ REFRESH reporting.mv_clientes_rfm")


def main():
    inicio_total = time.perf_counter()
    for titulo, modulo in PASOS:
        print(f"\n{'=' * 55}\n▶ {titulo}\n{'=' * 55}")
        inicio = time.perf_counter()
        modulo.main()
        print(f"⏱️  {time.perf_counter() - inicio:.1f} s")

    finalizar()
    print(f"\n🎉 TechNova generada en {time.perf_counter() - inicio_total:.1f} s")


if __name__ == "__main__":
    main()