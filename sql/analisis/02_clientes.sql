-- =====================================================================
--  TechNova - Análisis de CLIENTES
--  Conceptos: NTILE, LAG por cliente, cohortes, percentiles,
--             vista materializada RFM
-- =====================================================================


-- ---------------------------------------------------------------------
-- 1. Regla 80/20: ¿qué parte de la facturación deja el 20 % de mejores clientes?
--    NTILE(10) reparte a los clientes en 10 grupos iguales (deciles)
-- ---------------------------------------------------------------------
WITH gasto AS (
    SELECT id_cliente, SUM(importe_neto - importe_devuelto) AS total
    FROM reporting.v_lineas_venta
    GROUP BY id_cliente
),
deciles AS (
    SELECT id_cliente, total, NTILE(10) OVER (ORDER BY total DESC) AS decil
    FROM gasto
)
SELECT
    decil,
    COUNT(*)                                                 AS clientes,
    ROUND(SUM(total), 0)                                     AS facturacion,
    ROUND(100 * SUM(total) / SUM(SUM(total)) OVER (), 1)     AS pct_facturacion,
    ROUND(100 * SUM(SUM(total)) OVER (ORDER BY decil)
              / SUM(SUM(total)) OVER (), 1)                  AS pct_acumulado
FROM deciles
GROUP BY decil
ORDER BY decil;
-- Truco: SUM(SUM(total)) OVER () -> la función de ventana se aplica DESPUÉS del GROUP BY


-- ---------------------------------------------------------------------
-- 2. Análisis de cohortes: de los clientes que compraron por primera vez
--    en un trimestre, ¿cuántos vuelven a comprar en los trimestres siguientes?
-- ---------------------------------------------------------------------
WITH compras AS (
    SELECT DISTINCT id_cliente, date_trunc('quarter', dia)::date AS trimestre
    FROM reporting.v_lineas_venta
),
primera AS (
    SELECT id_cliente, MIN(trimestre) AS cohorte
    FROM compras
    GROUP BY id_cliente
),
actividad AS (
    SELECT
        p.cohorte,
        (EXTRACT(YEAR FROM c.trimestre) - EXTRACT(YEAR FROM p.cohorte)) * 4
          + (EXTRACT(QUARTER FROM c.trimestre) - EXTRACT(QUARTER FROM p.cohorte)) AS trimestres_despues,
        c.id_cliente
    FROM compras c
    JOIN primera p USING (id_cliente)
),
retencion AS (
    SELECT
        cohorte,
        COUNT(DISTINCT id_cliente) FILTER (WHERE trimestres_despues = 0) AS nuevos,
        COUNT(DISTINCT id_cliente) FILTER (WHERE trimestres_despues = 1) AS t1,
        COUNT(DISTINCT id_cliente) FILTER (WHERE trimestres_despues = 2) AS t2,
        COUNT(DISTINCT id_cliente) FILTER (WHERE trimestres_despues = 4) AS t4
    FROM actividad
    GROUP BY cohorte
)
-- Si el trimestre todavía no ha llegado, se muestra vacío (NULL) en vez de 0 %
SELECT
    r.cohorte,
    r.nuevos                                                                         AS clientes_nuevos,
    CASE WHEN r.cohorte + INTERVAL '3 months'  <= u.ultimo THEN ROUND(100.0 * r.t1 / r.nuevos, 1) END AS "T+1 %",
    CASE WHEN r.cohorte + INTERVAL '6 months'  <= u.ultimo THEN ROUND(100.0 * r.t2 / r.nuevos, 1) END AS "T+2 %",
    CASE WHEN r.cohorte + INTERVAL '12 months' <= u.ultimo THEN ROUND(100.0 * r.t4 / r.nuevos, 1) END AS "T+4 %"
FROM retencion r
CROSS JOIN (SELECT MAX(trimestre) AS ultimo FROM compras) u
ORDER BY r.cohorte;


-- ---------------------------------------------------------------------
-- 3. ¿Cada cuántos días vuelve a comprar un cliente?
--    LAG(fecha) OVER (PARTITION BY cliente) = su pedido anterior
-- ---------------------------------------------------------------------
WITH pedidos AS (
    SELECT DISTINCT id_cliente, id_pedido, dia
    FROM reporting.v_lineas_venta
),
intervalos AS (
    SELECT
        id_cliente,
        dia - LAG(dia) OVER (PARTITION BY id_cliente ORDER BY dia, id_pedido) AS dias_entre_compras
    FROM pedidos
)
SELECT
    ROUND(AVG(dias_entre_compras), 1)                                         AS media_dias,
    PERCENTILE_CONT(0.5)  WITHIN GROUP (ORDER BY dias_entre_compras)          AS mediana_dias,
    PERCENTILE_CONT(0.9)  WITHIN GROUP (ORDER BY dias_entre_compras)          AS percentil_90
FROM intervalos
WHERE dias_entre_compras IS NOT NULL;


-- ---------------------------------------------------------------------
-- 4. Segmentos RFM (vista materializada)
-- ---------------------------------------------------------------------
SELECT
    segmento,
    COUNT(*)                                   AS clientes,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct_clientes,
    ROUND(AVG(num_pedidos), 1)                 AS pedidos_medios,
    ROUND(AVG(gasto_total), 0)                 AS gasto_medio,
    ROUND(AVG(dias_sin_comprar), 0)            AS dias_sin_comprar,
    ROUND(SUM(gasto_total), 0)                 AS facturacion_total
FROM reporting.mv_clientes_rfm
GROUP BY segmento
ORDER BY facturacion_total DESC;


-- ---------------------------------------------------------------------
-- 5. Clientes "En riesgo" de más valor: candidatos a una campaña de recuperación
-- ---------------------------------------------------------------------
SELECT
    c.nombre || ' ' || c.apellidos AS cliente,
    c.email,
    n.nombre                      AS nivel,
    r.num_pedidos,
    r.gasto_total,
    r.ultima_compra,
    r.dias_sin_comprar,
    r.categoria_favorita
FROM reporting.mv_clientes_rfm r
JOIN oltp.cliente c         ON c.id_cliente = r.id_cliente
JOIN oltp.nivel_fidelidad n ON n.id_nivel   = c.id_nivel
WHERE r.segmento = 'En riesgo'
ORDER BY r.gasto_total DESC
LIMIT 20;


-- ---------------------------------------------------------------------
-- 6. Distribución por nivel de fidelidad y edad
-- ---------------------------------------------------------------------
SELECT
    n.nombre                                                        AS nivel,
    COUNT(*)                                                        AS clientes,
    ROUND(AVG(EXTRACT(YEAR FROM AGE(DATE '2025-12-31', c.fecha_nacimiento))), 1) AS edad_media,
    ROUND(AVG(c.puntos), 0)                                         AS puntos_medios
FROM oltp.cliente c
JOIN oltp.nivel_fidelidad n ON n.id_nivel = c.id_nivel
GROUP BY n.nombre, n.puntos_minimos
ORDER BY n.puntos_minimos;