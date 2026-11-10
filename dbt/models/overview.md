{% docs __overview__ %}
# TechNova Data Warehouse

Transformación de los datos que carga el ETL (`staging`) en un **esquema en estrella**
listo para el análisis y el dashboard.

| Capa | Esquema | Materialización | Contenido |
|---|---|---|---|
| Staging | `stg` | Vista | Las tablas de origen con nombres limpios |
| Intermedia | `int` | Vista | Cálculos reutilizables: líneas de venta con devoluciones, RFM |
| Marts | `marts` | Tabla | Dimensiones (`dim_`) y hechos (`fct_`) |
| Snapshots | `snapshots` | Tabla | Historial de cambios (SCD tipo 2) |

Usa el gráfico de linaje (botón azul abajo a la derecha) para ver de dónde sale cada tabla.
{% enddocs %}
