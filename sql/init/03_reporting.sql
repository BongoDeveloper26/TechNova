-- =====================================================================
--  TechNova Data Platform
--  03_reporting.sql  ->  Esquema "reporting": vistas de negocio
--
--  VISTA (VIEW): una consulta guardada con nombre. No guarda datos:
--  cada vez que la consultas se ejecuta de nuevo -> siempre actualizada.
--
--  VISTA MATERIALIZADA: guarda el RESULTADO en disco. Es mucho más rápida
--  de consultar, pero hay que refrescarla (REFRESH) cuando cambian los datos.
--  main.py la refresca al terminar de generar los datos.
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS reporting;

-- ---------------------------------------------------------------------
--  1. v_lineas_venta: una fila por línea vendida, con TODO el contexto
--     (desnormalizada: es la base de la mayoría de análisis)
-- ---------------------------------------------------------------------
CREATE VIEW reporting.v_lineas_venta AS
WITH devoluciones AS (
    SELECT id_linea,
           SUM(cantidad)                     AS unidades_devueltas,
           SUM(COALESCE(importe_reembolso, 0)) AS importe_devuelto
    FROM oltp.devolucion
    WHERE estado IN ('reembolsada', 'aceptada')
    GROUP BY id_linea
)
SELECT
    l.id_linea,
    pe.id_pedido,
    pe.fecha,
    pe.fecha::date                                   AS dia,
    pe.canal,
    pe.estado                                        AS estado_pedido,
    pe.id_cliente,
    pe.id_empleado,
    u.id_ubicacion,
    u.nombre                                         AS ubicacion,
    ci.nombre                                        AS ciudad_ubicacion,
    p.id_producto,
    p.sku,
    p.nombre                                         AS producto,
    sub.nombre                                       AS subcategoria,
    cat.nombre                                       AS categoria,
    m.nombre                                         AS marca,
    l.cantidad,
    l.precio_unitario,
    l.cantidad * l.precio_unitario                   AS importe_bruto,
    l.descuento,
    l.cantidad * l.precio_unitario - l.descuento     AS importe_neto,
    l.cantidad * p.coste                             AS coste_total,
    l.cantidad * l.precio_unitario - l.descuento
        - l.cantidad * p.coste                       AS margen,
    COALESCE(d.unidades_devueltas, 0)                AS unidades_devueltas,
    COALESCE(d.importe_devuelto, 0)                  AS importe_devuelto
FROM oltp.linea_pedido l
JOIN oltp.pedido    pe  ON pe.id_pedido     = l.id_pedido
JOIN oltp.producto  p   ON p.id_producto    = l.id_producto
JOIN oltp.categoria sub ON sub.id_categoria = p.id_categoria
JOIN oltp.categoria cat ON cat.id_categoria = sub.id_categoria_padre
JOIN oltp.marca     m   ON m.id_marca       = p.id_marca
LEFT JOIN oltp.ubicacion u  ON u.id_ubicacion = pe.id_ubicacion
LEFT JOIN oltp.ciudad    ci ON ci.id_ciudad   = u.id_ciudad
LEFT JOIN devoluciones   d  ON d.id_linea     = l.id_linea
WHERE pe.estado <> 'cancelado';

COMMENT ON VIEW reporting.v_lineas_venta IS
    'Una fila por línea de pedido no cancelado, con producto, categoría, marca, importes, margen y devoluciones.';

-- ---------------------------------------------------------------------
--  2. v_ventas_mensuales: KPIs por mes y canal
-- ---------------------------------------------------------------------
CREATE VIEW reporting.v_ventas_mensuales AS
SELECT
    date_trunc('month', fecha)::date                       AS mes,
    canal,
    COUNT(DISTINCT id_pedido)                              AS pedidos,
    COUNT(DISTINCT id_cliente)                             AS clientes,
    SUM(cantidad)                                          AS unidades,
    ROUND(SUM(importe_neto), 2)                            AS facturacion,
    ROUND(SUM(importe_devuelto), 2)                        AS devoluciones,
    ROUND(SUM(importe_neto - importe_devuelto), 2)         AS facturacion_neta,
    ROUND(SUM(margen), 2)                                  AS margen,
    ROUND(100 * SUM(margen) / NULLIF(SUM(importe_neto), 0), 2) AS margen_pct,
    ROUND(SUM(importe_neto) / COUNT(DISTINCT id_pedido), 2)    AS ticket_medio
FROM reporting.v_lineas_venta
GROUP BY 1, 2;

-- ---------------------------------------------------------------------
--  3. v_alertas_stock: qué hay que reponer y dónde
-- ---------------------------------------------------------------------
CREATE VIEW reporting.v_alertas_stock AS
SELECT
    u.nombre                       AS ubicacion,
    u.tipo,
    p.sku,
    p.nombre                       AS producto,
    s.cantidad,
    s.stock_minimo,
    s.stock_minimo - s.cantidad    AS unidades_faltan,
    CASE
        WHEN s.cantidad = 0                    THEN 'ROTURA'
        WHEN s.cantidad < s.stock_minimo / 2.0 THEN 'CRITICO'
        ELSE 'BAJO'
    END                            AS nivel_alerta
FROM oltp.stock s
JOIN oltp.ubicacion u ON u.id_ubicacion = s.id_ubicacion
JOIN oltp.producto  p ON p.id_producto  = s.id_producto
WHERE s.cantidad < s.stock_minimo
  AND p.activo;

-- ---------------------------------------------------------------------
--  4. mv_clientes_rfm (MATERIALIZADA): segmentación RFM de clientes
--
--     R = Recency   (¿hace cuánto compró por última vez?)
--     F = Frequency (¿cuántas veces compra?)
--     M = Monetary  (¿cuánto gasta?)
--     Cada métrica se puntúa de 1 a 5 con NTILE(5). La usaremos en la
--     Fase 7 para la segmentación de clientes con Machine Learning.
-- ---------------------------------------------------------------------
CREATE MATERIALIZED VIEW reporting.mv_clientes_rfm AS
WITH referencia AS (
    SELECT MAX(fecha)::date AS hoy FROM oltp.pedido
),
metricas AS (
    SELECT
        v.id_cliente,
        MIN(v.dia)                                    AS primera_compra,
        MAX(v.dia)                                    AS ultima_compra,
        COUNT(DISTINCT v.id_pedido)                   AS num_pedidos,
        ROUND(SUM(v.importe_neto - v.importe_devuelto), 2) AS gasto_total,
        MODE() WITHIN GROUP (ORDER BY v.canal)        AS canal_preferido,
        MODE() WITHIN GROUP (ORDER BY v.categoria)    AS categoria_favorita
    FROM reporting.v_lineas_venta v
    GROUP BY v.id_cliente
),
puntuaciones AS (
    SELECT
        m.*,
        r.hoy - m.ultima_compra                               AS dias_sin_comprar,
        NTILE(5) OVER (ORDER BY m.ultima_compra)              AS r_score,  -- más reciente = 5
        NTILE(5) OVER (ORDER BY m.num_pedidos, m.gasto_total) AS f_score,
        NTILE(5) OVER (ORDER BY m.gasto_total)                AS m_score
    FROM metricas m CROSS JOIN referencia r
)
SELECT
    p.*,
    ROUND(p.gasto_total / p.num_pedidos, 2) AS ticket_medio,
    CASE
        WHEN r_score >= 4 AND f_score >= 4 AND m_score >= 4 THEN 'Campeones'
        WHEN f_score >= 4 AND m_score >= 3                  THEN 'Leales'
        WHEN r_score >= 4 AND f_score <= 2                  THEN 'Nuevos'
        WHEN r_score <= 2 AND f_score >= 3                  THEN 'En riesgo'
        WHEN r_score <= 2 AND f_score <= 2                  THEN 'Perdidos'
        ELSE 'Potenciales'
    END                                     AS segmento
FROM puntuaciones p;

-- Índice único: permite REFRESH MATERIALIZED VIEW CONCURRENTLY
-- (refrescar sin bloquear a quien la está consultando)
CREATE UNIQUE INDEX idx_mv_clientes_rfm_cliente ON reporting.mv_clientes_rfm (id_cliente);
CREATE INDEX idx_mv_clientes_rfm_segmento       ON reporting.mv_clientes_rfm (segmento);