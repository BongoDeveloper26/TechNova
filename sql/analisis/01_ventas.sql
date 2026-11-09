-- =====================================================================
--  TechNova - Análisis de VENTAS
--  Conceptos: funciones de ventana (LAG, SUM OVER, AVG OVER, ROW_NUMBER),
--             CTEs, FILTER, frames (ROWS BETWEEN)
--  Ejecuta cada consulta por separado (selecciónala en pgAdmin y pulsa F5)
-- =====================================================================


-- ---------------------------------------------------------------------
-- 1. Crecimiento mensual: vs mes anterior (MoM) y vs mismo mes del año anterior (YoY)
--    LAG(x, n) = el valor de x n filas antes, según el ORDER BY de la ventana
-- ---------------------------------------------------------------------
WITH mensual AS (
    SELECT mes, SUM(facturacion_neta) AS facturacion
    FROM reporting.v_ventas_mensuales
    GROUP BY mes
)
SELECT
    mes,
    facturacion,
    LAG(facturacion, 1)  OVER (ORDER BY mes)                      AS mes_anterior,
    ROUND(100 * (facturacion / LAG(facturacion, 1)  OVER (ORDER BY mes) - 1), 1) AS crecimiento_mom_pct,
    LAG(facturacion, 12) OVER (ORDER BY mes)                      AS mismo_mes_anio_anterior,
    ROUND(100 * (facturacion / LAG(facturacion, 12) OVER (ORDER BY mes) - 1), 1) AS crecimiento_yoy_pct
FROM mensual
ORDER BY mes;


-- ---------------------------------------------------------------------
-- 2. Facturación acumulada a lo largo de cada año (running total)
--    PARTITION BY reinicia el acumulado al empezar un año nuevo
-- ---------------------------------------------------------------------
WITH mensual AS (
    SELECT mes, SUM(facturacion_neta) AS facturacion
    FROM reporting.v_ventas_mensuales
    GROUP BY mes
)
SELECT
    EXTRACT(YEAR FROM mes)::int AS anio,
    mes,
    facturacion,
    SUM(facturacion) OVER (PARTITION BY EXTRACT(YEAR FROM mes) ORDER BY mes) AS acumulado_anio,
    ROUND(100 * facturacion / SUM(facturacion) OVER (PARTITION BY EXTRACT(YEAR FROM mes)), 1) AS pct_del_anio
FROM mensual
ORDER BY mes;


-- ---------------------------------------------------------------------
-- 3. Media móvil de 7 días (suaviza los picos para ver la tendencia)
--    ROWS BETWEEN 6 PRECEDING AND CURRENT ROW = el día actual y los 6 anteriores
-- ---------------------------------------------------------------------
WITH diario AS (
    SELECT dia, COUNT(DISTINCT id_pedido) AS pedidos, SUM(importe_neto) AS facturacion
    FROM reporting.v_lineas_venta
    WHERE dia >= DATE '2025-10-01'
    GROUP BY dia
)
SELECT
    dia,
    TO_CHAR(dia, 'TMDay')                                         AS dia_semana,
    pedidos,
    ROUND(AVG(pedidos) OVER (ORDER BY dia ROWS BETWEEN 6 PRECEDING AND CURRENT ROW), 1) AS media_movil_7d,
    ROUND(facturacion, 2)                                         AS facturacion
FROM diario
ORDER BY dia;


-- ---------------------------------------------------------------------
-- 4. Top 3 productos más vendidos de cada categoría
--    ROW_NUMBER numera las filas dentro de cada partición (categoría)
-- ---------------------------------------------------------------------
WITH ventas_producto AS (
    SELECT categoria, producto, SUM(cantidad) AS unidades, ROUND(SUM(importe_neto), 2) AS facturacion
    FROM reporting.v_lineas_venta
    GROUP BY categoria, producto
),
ranking AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY categoria ORDER BY facturacion DESC) AS puesto
    FROM ventas_producto
)
SELECT categoria, puesto, producto, unidades, facturacion
FROM ranking
WHERE puesto <= 3
ORDER BY categoria, puesto;


-- ---------------------------------------------------------------------
-- 5. ¿Compensa el Black Friday? Black Week vs la semana anterior
--    FILTER (WHERE ...) = agregación condicional, más legible que CASE WHEN
-- ---------------------------------------------------------------------
WITH semanas AS (
    SELECT
        p.nombre                   AS campania,
        p.fecha_inicio,
        p.fecha_fin,
        p.fecha_inicio - 7         AS inicio_anterior,
        p.fecha_inicio - 1         AS fin_anterior
    FROM oltp.promocion p
    WHERE p.nombre LIKE 'Black Friday%'
)
SELECT
    s.campania,
    COUNT(DISTINCT v.id_pedido) FILTER (WHERE v.dia BETWEEN s.fecha_inicio AND s.fecha_fin)       AS pedidos_bf,
    COUNT(DISTINCT v.id_pedido) FILTER (WHERE v.dia BETWEEN s.inicio_anterior AND s.fin_anterior) AS pedidos_antes,
    ROUND(SUM(v.importe_neto) FILTER (WHERE v.dia BETWEEN s.fecha_inicio AND s.fecha_fin), 0)       AS facturacion_bf,
    ROUND(SUM(v.importe_neto) FILTER (WHERE v.dia BETWEEN s.inicio_anterior AND s.fin_anterior), 0) AS facturacion_antes,
    ROUND(100 * SUM(v.margen) FILTER (WHERE v.dia BETWEEN s.fecha_inicio AND s.fecha_fin)
              / SUM(v.importe_neto) FILTER (WHERE v.dia BETWEEN s.fecha_inicio AND s.fecha_fin), 1)       AS margen_pct_bf,
    ROUND(100 * SUM(v.margen) FILTER (WHERE v.dia BETWEEN s.inicio_anterior AND s.fin_anterior)
              / SUM(v.importe_neto) FILTER (WHERE v.dia BETWEEN s.inicio_anterior AND s.fin_anterior), 1) AS margen_pct_antes
FROM semanas s
JOIN reporting.v_lineas_venta v ON v.dia BETWEEN s.inicio_anterior AND s.fecha_fin
GROUP BY s.campania
ORDER BY s.campania;


-- ---------------------------------------------------------------------
-- 6. Análisis de Pareto: ¿cuántos productos generan el 80 % de la facturación?
--    SUM() OVER (ORDER BY ... DESC) = acumulado de mayor a menor
-- ---------------------------------------------------------------------
WITH por_producto AS (
    SELECT producto, SUM(importe_neto) AS facturacion
    FROM reporting.v_lineas_venta
    GROUP BY producto
),
acumulado AS (
    SELECT
        producto,
        facturacion,
        ROW_NUMBER() OVER (ORDER BY facturacion DESC)                         AS puesto,
        100 * SUM(facturacion) OVER (ORDER BY facturacion DESC) / SUM(facturacion) OVER () AS pct_acumulado
    FROM por_producto
)
SELECT
    COUNT(*) FILTER (WHERE pct_acumulado <= 80)                                     AS productos_80pct,
    COUNT(*)                                                                        AS productos_total,
    ROUND(100.0 * COUNT(*) FILTER (WHERE pct_acumulado <= 80) / COUNT(*), 1)        AS pct_del_catalogo
FROM acumulado;


-- ---------------------------------------------------------------------
-- 7. Ventas por hora del día y canal (¿cuándo compra la gente?)
-- ---------------------------------------------------------------------
SELECT
    EXTRACT(HOUR FROM fecha)::int                     AS hora,
    COUNT(DISTINCT id_pedido) FILTER (WHERE canal = 'web')    AS pedidos_web,
    COUNT(DISTINCT id_pedido) FILTER (WHERE canal = 'tienda') AS pedidos_tienda
FROM reporting.v_lineas_venta
GROUP BY 1
ORDER BY 1;