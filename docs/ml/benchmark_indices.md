# Benchmark de índices

Comparación de tiempos de ejecución con y sin los 28 índices definidos en `sql/init/02_indices.sql`. Cada consulta se ejecuta 5 veces con `EXPLAIN ANALYZE` y se toma la mediana.

Los índices se eliminan dentro de una transacción que después se deshace (`ROLLBACK`), así que la base de datos no se modifica.

| Consulta | Sin índices | Acceso | Con índices | Acceso | Mejora |
|---|---:|---|---:|---|---:|
| Historial de pedidos de un cliente | 4.49 ms | Seq Scan | 0.09 ms | Bitmap Heap Scan + Bitmap Index Scan | x49 |
| Líneas vendidas de un producto | 6.93 ms | Seq Scan | 0.00 ms | Bitmap Heap Scan + Bitmap Index Scan | x1,732 |
| Pagos de un pedido | 4.81 ms | Seq Scan | 0.00 ms | Index Scan | x1,203 |
| Pedidos de un día concreto | 7.29 ms | Seq Scan | 0.18 ms | Index Scan | x41 |
| Login por email (sin mayúsculas) | 10.22 ms | Seq Scan | 0.01 ms | Index Scan | x2,045 |
| Devoluciones pendientes (índice parcial) | 0.57 ms | Seq Scan | 0.04 ms | Index Scan | x15 |
| Último pedido de 2.000 clientes (subconsulta correlacionada) | 7462.05 ms | Index Only Scan + Seq Scan | 2.37 ms | Index Only Scan | x3,151 |
| Devoluciones de los pedidos de un cliente (3 JOIN) | 13.16 ms | Seq Scan + Index Scan | 0.52 ms | Bitmap Heap Scan + Bitmap Index Scan + Index Scan | x25 |

**Cómo leer la tabla**

- `Seq Scan`: PostgreSQL recorre la tabla entera fila a fila.
- `Index Scan` / `Index Only Scan`: va directo a las filas usando el índice.
- `Bitmap Heap Scan`: usa el índice para marcar qué bloques leer y luego los lee de una vez (lo elige cuando hay bastantes filas que devolver).

Los tiempos dependen del equipo; lo importante es la diferencia relativa. Con más datos la diferencia crece: un `Seq Scan` es O(n) y un índice B-tree es O(log n).