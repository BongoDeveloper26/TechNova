"""
benchmark_indices.py -> Mide cuánto mejoran los índices el rendimiento.

Cómo funciona:
  1. Ejecuta varias consultas típicas CON los índices de sql/init/02_indices.sql.
  2. Abre una transacción, BORRA esos índices y repite las mismas consultas.
  3. Hace ROLLBACK: en PostgreSQL hasta el DROP INDEX es transaccional,
     así que los índices vuelven a estar como estaban. No se toca nada.
  4. Guarda los resultados en docs/benchmark_indices.md

Uso (desde la raíz del proyecto):
    python benchmarks/benchmark_indices.py
"""
import json
import re
import statistics
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "data_generator"))
from db import get_connection  # noqa: E402

FICHERO_INDICES = RAIZ / "sql" / "init" / "02_indices.sql"
FICHERO_RESULTADO = RAIZ / "docs" / "benchmark_indices.md"
REPETICIONES = 5

CONSULTAS = [
    ("Historial de pedidos de un cliente",
     "SELECT * FROM pedido WHERE id_cliente = 1234 ORDER BY fecha DESC"),
    ("Líneas vendidas de un producto",
     "SELECT * FROM linea_pedido WHERE id_producto = 42"),
    ("Pagos de un pedido",
     "SELECT * FROM pago WHERE id_pedido = 15000"),
    ("Pedidos de un día concreto",
     "SELECT * FROM pedido WHERE fecha >= '2024-11-29' AND fecha < '2024-11-30'"),
    ("Login por email (sin mayúsculas)",
     "SELECT * FROM cliente WHERE LOWER(email) = LOWER('Maria.Garcia@gmail.com')"),
    ("Devoluciones pendientes (índice parcial)",
     "SELECT * FROM devolucion WHERE estado = 'solicitada' ORDER BY fecha"),
    ("Último pedido de cada cliente (subconsulta correlacionada)",
     "SELECT c.id_cliente, (SELECT MAX(p.fecha) FROM pedido p WHERE p.id_cliente = c.id_cliente) "
     "FROM cliente c"),
    ("Devoluciones de los pedidos de un cliente (3 JOIN)",
     "SELECT d.* FROM pedido pe JOIN linea_pedido l ON l.id_pedido = pe.id_pedido "
     "JOIN devolucion d ON d.id_linea = l.id_linea WHERE pe.id_cliente = 1234"),
]


def nombres_indices():
    """Lee los nombres de los índices del fichero SQL (así no hay que mantener dos listas)."""
    texto = FICHERO_INDICES.read_text(encoding="utf-8")
    return re.findall(r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(\w+)", texto, flags=re.IGNORECASE)


def tipo_de_acceso(plan, encontrados=None):
    """Recorre el plan y devuelve cómo se lee cada tabla (Seq Scan, Index Scan...)."""
    if encontrados is None:
        encontrados = []
    if "Scan" in plan["Node Type"] and plan["Node Type"] not in encontrados:
        encontrados.append(plan["Node Type"])
    for hijo in plan.get("Plans", []):
        tipo_de_acceso(hijo, encontrados)
    return " + ".join(encontrados)


def medir(cur, sql):
    tiempos = []
    for _ in range(REPETICIONES):
        cur.execute(f"EXPLAIN (ANALYZE, FORMAT JSON) {sql}")
        resultado = cur.fetchone()[0]
        resultado = json.loads(resultado) if isinstance(resultado, str) else resultado
        tiempos.append(resultado[0]["Execution Time"])
    return statistics.median(tiempos), tipo_de_acceso(resultado[0]["Plan"])


def main():
    indices = nombres_indices()
    resultados = []

    with get_connection() as conn, conn.cursor() as cur:
        print(f"Midiendo {len(CONSULTAS)} consultas ({REPETICIONES} repeticiones, mediana)...\n")

        con_indices = [medir(cur, sql) for _, sql in CONSULTAS]

        # --- Sin índices, dentro de una transacción que luego se deshace ---
        for nombre in indices:
            cur.execute(f"DROP INDEX IF EXISTS oltp.{nombre}")
        sin_indices = [medir(cur, sql) for _, sql in CONSULTAS]
        conn.rollback()  # los índices vuelven a existir

        for (titulo, _), (t_con, acceso_con), (t_sin, acceso_sin) in zip(CONSULTAS, con_indices, sin_indices):
            mejora = t_sin / t_con if t_con > 0 else float("inf")
            resultados.append((titulo, t_sin, acceso_sin, t_con, acceso_con, mejora))
            print(f"{titulo:<58} {t_sin:>9.2f} ms -> {t_con:>8.2f} ms   x{mejora:,.0f}")

    escribir_informe(resultados, len(indices))
    print(f"\nInforme guardado en {FICHERO_RESULTADO.relative_to(RAIZ)}")


def escribir_informe(resultados, num_indices):
    lineas = [
        "# Benchmark de índices",
        "",
        f"Comparación de tiempos de ejecución con y sin los {num_indices} índices definidos en "
        "`sql/init/02_indices.sql`. Cada consulta se ejecuta "
        f"{REPETICIONES} veces con `EXPLAIN ANALYZE` y se toma la mediana.",
        "",
        "Los índices se eliminan dentro de una transacción que después se deshace (`ROLLBACK`), "
        "así que la base de datos no se modifica.",
        "",
        "| Consulta | Sin índices | Acceso | Con índices | Acceso | Mejora |",
        "|---|---:|---|---:|---|---:|",
    ]
    for titulo, t_sin, a_sin, t_con, a_con, mejora in resultados:
        lineas.append(f"| {titulo} | {t_sin:.2f} ms | {a_sin} | {t_con:.2f} ms | {a_con} | x{mejora:,.0f} |")
    lineas += [
        "",
        "**Cómo leer la tabla**",
        "",
        "- `Seq Scan`: PostgreSQL recorre la tabla entera fila a fila.",
        "- `Index Scan` / `Index Only Scan`: va directo a las filas usando el índice.",
        "- `Bitmap Heap Scan`: usa el índice para marcar qué bloques leer y luego los lee de una vez "
        "(lo elige cuando hay bastantes filas que devolver).",
        "",
        "Los tiempos dependen del equipo; lo importante es la diferencia relativa. "
        "Con más datos la diferencia crece: un `Seq Scan` es O(n) y un índice B-tree es O(log n).",
        "",
    ]
    FICHERO_RESULTADO.parent.mkdir(exist_ok=True)
    FICHERO_RESULTADO.write_text("\n".join(lineas), encoding="utf-8")


if __name__ == "__main__":
    main()