-- =====================================================================
--  TechNova - Análisis de OPERACIONES
--  Conceptos: RANK / DENSE_RANK, PERCENTILE_CONT, CTE recursiva,
--             conversión de divisas, vistas
-- =====================================================================


-- ---------------------------------------------------------------------
-- 1. Ranking de vendedores en cada tienda (año 2025)
--    RANK: empates comparten puesto y se salta el siguiente (1, 1, 3)
--    DENSE_RANK: empates comparten puesto sin saltos (1, 1, 2)
-- ---------------------------------------------------------------------
WITH ventas_vendedor AS (
    SELECT
        v.ubicacion                          AS tienda,
        e.nombre || ' ' || e.apellidos       AS vendedor,
        COUNT(DISTINCT v.id_pedido)          AS pedidos,
        ROUND(SUM(v.importe_neto), 2)        AS facturacion
    FROM reporting.v_lineas_venta v
    JOIN oltp.empleado e ON e.id_empleado = v.id_empleado
    WHERE v.canal = 'tienda' AND v.dia >= DATE '2025-01-01'
    GROUP BY v.ubicacion, e.id_empleado, e.nombre, e.apellidos
)
SELECT
    tienda,
    RANK() OVER (PARTITION BY tienda ORDER BY facturacion DESC) AS puesto,
    vendedor,
    pedidos,
    facturacion,
    ROUND(100 * facturacion / SUM(facturacion) OVER (PARTITION BY tienda), 1) AS pct_tienda
FROM ventas_vendedor
ORDER BY tienda, puesto;


-- ---------------------------------------------------------------------
-- 2. Tiempos de entrega por transportista: media, mediana y percentil 90
--    El P90 es lo que miran las empresas: "el 90 % llega en menos de X días"
-- ---------------------------------------------------------------------
SELECT
    transportista,
    COUNT(*)                                                                   AS envios,
    ROUND(AVG(EXTRACT(EPOCH FROM fecha_entrega - fecha_envio) / 86400)::numeric, 2) AS media_dias,
    ROUND((PERCENTILE_CONT(0.5) WITHIN GROUP (
        ORDER BY EXTRACT(EPOCH FROM fecha_entrega - fecha_envio) / 86400))::numeric, 2) AS mediana_dias,
    ROUND((PERCENTILE_CONT(0.9) WITHIN GROUP (
        ORDER BY EXTRACT(EPOCH FROM fecha_entrega - fecha_envio) / 86400))::numeric, 2) AS p90_dias,
    ROUND(100.0 * (SELECT COUNT(*) FROM oltp.envio i
                   WHERE i.transportista = e.transportista AND i.estado = 'incidencia')
          / COUNT(*), 2)                                                       AS pct_incidencias
FROM oltp.envio e
WHERE estado = 'entregado'
GROUP BY transportista
ORDER BY p90_dias;


-- ---------------------------------------------------------------------
-- 3. Tasa de devolución por subcategoría y canal
-- ---------------------------------------------------------------------
SELECT
    subcategoria,
    ROUND(100.0 * SUM(unidades_devueltas) FILTER (WHERE canal = 'web')
               / SUM(cantidad) FILTER (WHERE canal = 'web'), 2)    AS pct_devolucion_web,
    ROUND(100.0 * SUM(unidades_devueltas) FILTER (WHERE canal = 'tienda')
               / SUM(cantidad) FILTER (WHERE canal = 'tienda'), 2) AS pct_devolucion_tienda,
    ROUND(SUM(importe_devuelto), 0)                                AS importe_devuelto
FROM reporting.v_lineas_venta
GROUP BY subcategoria
ORDER BY importe_devuelto DESC;


-- ---------------------------------------------------------------------
-- 4. Gasto en proveedores convertido a euros
--    coste_unitario está en la moneda del proveedor; tipo_cambio = moneda por 1 €
-- ---------------------------------------------------------------------
SELECT
    pr.nombre                                                     AS proveedor,
    pr.moneda,
    EXTRACT(YEAR FROM pc.fecha_pedido)::int                       AS anio,
    COUNT(DISTINCT pc.id_pedido_compra)                           AS pedidos,
    ROUND(SUM(lc.cantidad * lc.coste_unitario), 2)                AS importe_moneda_original,
    ROUND(SUM(lc.cantidad * lc.coste_unitario / pc.tipo_cambio), 2) AS importe_eur,
    ROUND(AVG(pc.fecha_recepcion - pc.fecha_pedido), 1)           AS dias_entrega_medios
FROM oltp.pedido_compra pc
JOIN oltp.proveedor pr     ON pr.id_proveedor     = pc.id_proveedor
JOIN oltp.linea_compra lc  ON lc.id_pedido_compra = pc.id_pedido_compra
WHERE pc.estado = 'recibido'
GROUP BY pr.nombre, pr.moneda, anio
ORDER BY pr.nombre, anio;


-- ---------------------------------------------------------------------
-- 5. Alertas de stock en almacenes (vista)
-- ---------------------------------------------------------------------
SELECT *
FROM reporting.v_alertas_stock
WHERE tipo = 'almacen'
ORDER BY nivel_alerta, unidades_faltan DESC;


-- ---------------------------------------------------------------------
-- 6. Organigrama completo con CTE RECURSIVA
--    Parte de la raíz (sin jefe) y va bajando nivel a nivel por id_jefe
-- ---------------------------------------------------------------------
WITH RECURSIVE organigrama AS (
    -- caso base: el director general
    SELECT id_empleado, nombre || ' ' || apellidos AS empleado, puesto, id_ubicacion,
           1 AS nivel, (nombre || ' ' || apellidos)::text AS ruta
    FROM oltp.empleado
    WHERE id_jefe IS NULL

    UNION ALL

    -- paso recursivo: los subordinados de los que ya tenemos
    SELECT e.id_empleado, e.nombre || ' ' || e.apellidos, e.puesto, e.id_ubicacion,
           o.nivel + 1, o.ruta || ' > ' || e.nombre || ' ' || e.apellidos
    FROM oltp.empleado e
    JOIN organigrama o ON e.id_jefe = o.id_empleado
)
SELECT
    REPEAT('    ', nivel - 1) || empleado AS organigrama,
    puesto,
    u.nombre                              AS ubicacion,
    nivel
FROM organigrama o
JOIN oltp.ubicacion u ON u.id_ubicacion = o.id_ubicacion
ORDER BY ruta;


-- ---------------------------------------------------------------------
-- 7. Árbol de categorías con CTE recursiva (ruta completa)
-- ---------------------------------------------------------------------
WITH RECURSIVE arbol AS (
    SELECT id_categoria, nombre, nombre::text AS ruta, 1 AS nivel
    FROM oltp.categoria
    WHERE id_categoria_padre IS NULL
    UNION ALL
    SELECT c.id_categoria, c.nombre, a.ruta || ' > ' || c.nombre, a.nivel + 1
    FROM oltp.categoria c
    JOIN arbol a ON c.id_categoria_padre = a.id_categoria
)
SELECT a.ruta, a.nivel, COUNT(p.id_producto) AS productos
FROM arbol a
LEFT JOIN oltp.producto p ON p.id_categoria = a.id_categoria
GROUP BY a.ruta, a.nivel
ORDER BY a.ruta;