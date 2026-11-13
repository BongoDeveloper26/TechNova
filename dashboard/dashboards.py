"""
dashboards.py -> DEFINICIÓN de los dashboards de TechNova ("dashboards como código").

Cada gráfico (en Metabase se llama "pregunta" o "card") tiene:
  - nombre:  el título que se ve en el dashboard
  - tipo:    cómo se dibuja: scalar (un número), line, bar, row (barras horizontales),
             pie (tarta), table (tabla)
  - sql:     la consulta. Todas leen del esquema en estrella (marts) que construye dbt
  - ejes:    para gráficos: qué columna va en el eje X (dimensiones) y cuál en el Y (métricas)
  - euros / porcentaje: columnas que se muestran con formato de € o de %
  - pos:     (fila, columna, ancho, alto) en la rejilla del dashboard, que tiene 24 columnas

crear_dashboard.py lee este fichero y lo crea todo en Metabase a través de su API.
Para cambiar un gráfico, se cambia aquí y se vuelve a ejecutar el script.
"""

# Año más reciente con ventas (para los indicadores "del último año")
ULTIMO_ANIO = "(SELECT MAX(f.anio) FROM marts.fct_ventas v JOIN marts.dim_fecha f USING (id_fecha))"

# =====================================================================
#  DASHBOARD 1: VENTAS Y CLIENTES
# =====================================================================
VENTAS = {
    "nombre": "TechNova - Ventas y clientes",
    "descripcion": "Evolución de las ventas, márgenes, campañas y segmentación de clientes",
    "tarjetas": [
        # ---------------- Fila de indicadores (KPI) ----------------
        {
            "nombre": "Facturación neta (último año)",
            "tipo": "scalar", "euros": ["facturacion"], "pos": (0, 0, 6, 3),
            "sql": f"""
SELECT ROUND(SUM(v.importe_neto_final), 0) AS facturacion
FROM marts.fct_ventas v
JOIN marts.dim_fecha f USING (id_fecha)
WHERE f.anio = {ULTIMO_ANIO}""",
        },
        {
            "nombre": "Pedidos (último año)",
            "tipo": "scalar", "pos": (0, 6, 6, 3),
            "sql": f"""
SELECT COUNT(*) AS pedidos
FROM marts.fct_pedidos p
JOIN marts.dim_fecha f USING (id_fecha)
WHERE f.anio = {ULTIMO_ANIO} AND p.estado <> 'cancelado'""",
        },
        {
            "nombre": "Ticket medio (último año)",
            "tipo": "scalar", "euros": ["ticket_medio"], "pos": (0, 12, 6, 3),
            "sql": f"""
SELECT ROUND(AVG(p.importe_neto), 2) AS ticket_medio
FROM marts.fct_pedidos p
JOIN marts.dim_fecha f USING (id_fecha)
WHERE f.anio = {ULTIMO_ANIO} AND p.estado <> 'cancelado'""",
        },
        {
            "nombre": "Margen bruto % (último año)",
            "tipo": "scalar", "porcentaje": ["margen_pct"], "pos": (0, 18, 6, 3),
            "sql": f"""
SELECT ROUND(SUM(v.margen) / SUM(v.importe_neto), 4) AS margen_pct
FROM marts.fct_ventas v
JOIN marts.dim_fecha f USING (id_fecha)
WHERE f.anio = {ULTIMO_ANIO}""",
        },
        # ---------------- Evolución ----------------
        {
            "nombre": "Facturación neta mensual por canal",
            "tipo": "line", "ejes": (["mes", "canal"], ["facturacion"]), "euros": ["facturacion"],
            "pos": (3, 0, 24, 7),
            "sql": """
SELECT f.anio_mes AS mes, v.canal, ROUND(SUM(v.importe_neto_final), 0) AS facturacion
FROM marts.fct_ventas v
JOIN marts.dim_fecha f USING (id_fecha)
GROUP BY f.anio_mes, v.canal
ORDER BY f.anio_mes, v.canal""",
        },
        # ---------------- Producto ----------------
        {
            "nombre": "Facturación por categoría",
            "tipo": "row", "ejes": (["categoria"], ["facturacion"]), "euros": ["facturacion"],
            "pos": (10, 0, 12, 6),
            "sql": """
SELECT p.categoria, ROUND(SUM(v.importe_neto_final), 0) AS facturacion
FROM marts.fct_ventas v
JOIN marts.dim_producto p USING (id_producto)
GROUP BY p.categoria
ORDER BY facturacion DESC""",
        },
        {
            "nombre": "Margen % por categoría",
            "tipo": "bar", "ejes": (["categoria"], ["margen_pct"]), "porcentaje": ["margen_pct"],
            "pos": (10, 12, 12, 6),
            "sql": """
SELECT p.categoria, ROUND(SUM(v.margen) / SUM(v.importe_neto), 4) AS margen_pct
FROM marts.fct_ventas v
JOIN marts.dim_producto p USING (id_producto)
GROUP BY p.categoria
ORDER BY margen_pct DESC""",
        },
        # ---------------- Campañas ----------------
        # Black Friday en dos gráficos: la facturación y el margen tienen escalas muy distintas
        {
            "nombre": "Black Friday: facturación",
            "tipo": "bar", "ejes": (["anio", "periodo"], ["facturacion"]), "euros": ["facturacion"],
            "pos": (16, 0, 6, 6),
            "sql": """
WITH semanas AS (
    SELECT campania, fecha_inicio, fecha_fin
    FROM stg.stg_promociones
    WHERE campania = 'Black Friday'
)
SELECT
    EXTRACT(YEAR FROM s.fecha_inicio)::int::text AS anio,
    CASE WHEN f.fecha >= s.fecha_inicio THEN '2. Black Week' ELSE '1. Semana anterior' END AS periodo,
    ROUND(SUM(v.importe_neto), 0) AS facturacion
FROM semanas s
JOIN marts.dim_fecha f  ON f.fecha BETWEEN s.fecha_inicio - 7 AND s.fecha_fin
JOIN marts.fct_ventas v ON v.id_fecha = f.id_fecha
GROUP BY 1, 2
ORDER BY 1, 2""",
        },
        {
            "nombre": "Black Friday: margen %",
            "tipo": "bar", "ejes": (["anio", "periodo"], ["margen_pct"]), "porcentaje": ["margen_pct"],
            "pos": (16, 6, 6, 6),
            "sql": """
WITH semanas AS (
    SELECT campania, fecha_inicio, fecha_fin
    FROM stg.stg_promociones
    WHERE campania = 'Black Friday'
)
SELECT
    EXTRACT(YEAR FROM s.fecha_inicio)::int::text AS anio,
    CASE WHEN f.fecha >= s.fecha_inicio THEN '2. Black Week' ELSE '1. Semana anterior' END AS periodo,
    ROUND(SUM(v.margen) / NULLIF(SUM(v.importe_neto), 0), 4) AS margen_pct
FROM semanas s
JOIN marts.dim_fecha f  ON f.fecha BETWEEN s.fecha_inicio - 7 AND s.fecha_fin
JOIN marts.fct_ventas v ON v.id_fecha = f.id_fecha
GROUP BY 1, 2
ORDER BY 1, 2""",
        },
        {
            "nombre": "Pedidos por día de la semana y canal",
            "tipo": "bar", "ejes": (["dia", "canal"], ["pedidos"]), "pos": (16, 12, 12, 6),
            "sql": """
SELECT f.dia_semana || '. ' || f.nombre_dia AS dia, p.canal, COUNT(*) AS pedidos
FROM marts.fct_pedidos p
JOIN marts.dim_fecha f USING (id_fecha)
WHERE p.estado <> 'cancelado'
GROUP BY f.dia_semana, f.nombre_dia, p.canal
ORDER BY f.dia_semana, p.canal""",
        },
        # ---------------- Clientes ----------------
        {
            "nombre": "Clientes por segmento RFM",
            "tipo": "pie", "ejes": (["segmento_rfm"], ["clientes"]), "pos": (22, 0, 8, 7),
            "sql": """
SELECT segmento_rfm, COUNT(*) AS clientes
FROM marts.dim_cliente
WHERE segmento_rfm <> 'Sin compras'
GROUP BY segmento_rfm
ORDER BY clientes DESC""",
        },
        {
            "nombre": "Facturación por segmento RFM",
            "tipo": "row", "ejes": (["segmento_rfm"], ["facturacion"]), "euros": ["facturacion"],
            "pos": (22, 8, 8, 7),
            "sql": """
SELECT c.segmento_rfm, ROUND(SUM(v.importe_neto_final), 0) AS facturacion
FROM marts.fct_ventas v
JOIN marts.dim_cliente c USING (id_cliente)
GROUP BY c.segmento_rfm
ORDER BY facturacion DESC""",
        },
        {
            "nombre": "Clientes por rango de edad",
            "tipo": "bar", "ejes": (["rango_edad"], ["clientes"]), "pos": (22, 16, 8, 7),
            "sql": """
SELECT rango_edad, COUNT(*) AS clientes
FROM marts.dim_cliente
WHERE num_pedidos > 0
GROUP BY rango_edad
ORDER BY rango_edad""",
        },
        {
            "nombre": "Top 10 productos por facturación",
            "tipo": "table", "euros": ["facturacion", "margen"], "pos": (29, 0, 24, 7),
            "sql": """
SELECT p.producto, p.marca, p.categoria,
       SUM(v.cantidad)                     AS unidades,
       ROUND(SUM(v.importe_neto_final), 0) AS facturacion,
       ROUND(SUM(v.margen), 0)             AS margen
FROM marts.fct_ventas v
JOIN marts.dim_producto p USING (id_producto)
GROUP BY p.producto, p.marca, p.categoria
ORDER BY facturacion DESC
LIMIT 10""",
        },
    ],
}

# =====================================================================
#  DASHBOARD 2: OPERACIONES Y CALIDAD DEL DATO
# =====================================================================
OPERACIONES = {
    "nombre": "TechNova - Operaciones",
    "descripcion": "Stock, envíos, devoluciones, proveedores y salud del pipeline de datos",
    "tarjetas": [
        # ---------------- KPIs ----------------
        {
            "nombre": "Valor del stock",
            "tipo": "scalar", "euros": ["valor_stock"], "pos": (0, 0, 6, 3),
            "sql": "SELECT ROUND(SUM(valor_stock_eur), 0) AS valor_stock FROM marts.fct_stock",
        },
        {
            "nombre": "Productos en rotura de stock",
            "tipo": "scalar", "pos": (0, 6, 6, 3),
            "sql": """
SELECT COUNT(*) AS en_rotura
FROM marts.fct_stock s
JOIN marts.dim_producto p USING (id_producto)
WHERE s.nivel_alerta = 'ROTURA' AND p.activo""",
        },
        {
            "nombre": "Tasa de devolución (unidades)",
            "tipo": "scalar", "porcentaje": ["tasa_devolucion"], "pos": (0, 12, 6, 3),
            "sql": "SELECT ROUND(SUM(unidades_devueltas)::numeric / SUM(cantidad), 4) AS tasa_devolucion FROM marts.fct_ventas",
        },
        {
            "nombre": "Envíos entregados en 3 días o menos",
            "tipo": "scalar", "porcentaje": ["pct_rapidos"], "pos": (0, 18, 6, 3),
            "sql": """
SELECT ROUND(AVG((dias_hasta_entrega <= 3)::int), 4) AS pct_rapidos
FROM marts.fct_pedidos
WHERE dias_hasta_entrega IS NOT NULL""",
        },
        # ---------------- Logística ----------------
        {
            "nombre": "Días hasta la entrega por transportista (media y P90)",
            "tipo": "bar", "ejes": (["transportista"], ["media_dias", "p90_dias"]), "pos": (3, 0, 12, 6),
            "sql": """
SELECT transportista,
       ROUND(AVG(dias_hasta_entrega), 2) AS media_dias,
       ROUND((PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY dias_hasta_entrega))::numeric, 2) AS p90_dias
FROM marts.fct_pedidos
WHERE dias_hasta_entrega IS NOT NULL
GROUP BY transportista
ORDER BY p90_dias""",
        },
        {
            "nombre": "Tasa de devolución por subcategoría",
            "tipo": "row", "ejes": (["subcategoria"], ["tasa_devolucion"]), "porcentaje": ["tasa_devolucion"],
            "pos": (3, 12, 12, 6),
            "sql": """
SELECT p.subcategoria, ROUND(SUM(v.unidades_devueltas)::numeric / SUM(v.cantidad), 4) AS tasa_devolucion
FROM marts.fct_ventas v
JOIN marts.dim_producto p USING (id_producto)
GROUP BY p.subcategoria
ORDER BY tasa_devolucion DESC
LIMIT 10""",
        },
        # ---------------- Stock y proveedores ----------------
        {
            "nombre": "Alertas de stock en almacenes",
            "tipo": "table", "pos": (9, 0, 12, 7),
            "sql": """
SELECT u.ubicacion AS almacen, p.producto, s.cantidad, s.stock_minimo, s.unidades_faltan, s.nivel_alerta
FROM marts.fct_stock s
JOIN marts.dim_producto p  USING (id_producto)
JOIN marts.dim_ubicacion u USING (id_ubicacion)
WHERE u.tipo = 'almacen' AND s.nivel_alerta <> 'OK' AND p.activo
ORDER BY CASE s.nivel_alerta WHEN 'ROTURA' THEN 1 WHEN 'CRITICO' THEN 2 ELSE 3 END,
         s.unidades_faltan DESC
LIMIT 50""",
        },
        {
            "nombre": "Desviación media de las tarifas de proveedor (%)",
            "tipo": "line", "ejes": (["fecha", "proveedor"], ["desviacion_pct"]), "pos": (9, 12, 12, 7),
            "sql": """
SELECT t.fecha_tarifa AS fecha, pr.proveedor, ROUND(AVG(t.desviacion_pct) / 100, 4) AS desviacion_pct
FROM marts.fct_tarifas_proveedor t
JOIN marts.dim_proveedor pr USING (id_proveedor)
-- Solo los últimos 30 días con tarifas (si no, mezcla periodos muy separados en el eje)
WHERE t.fecha_tarifa >= (SELECT MAX(fecha_tarifa) FROM marts.fct_tarifas_proveedor) - 30
GROUP BY t.fecha_tarifa, pr.proveedor
ORDER BY t.fecha_tarifa, pr.proveedor""",
            "porcentaje": ["desviacion_pct"],
        },
        # ---------------- Salud del pipeline ----------------
        {
            "nombre": "Últimas ejecuciones del ETL",
            "tipo": "table", "pos": (16, 0, 14, 7),
            "sql": """
SELECT e.id_ejecucion, e.fecha_proceso, e.estado,
       to_char(e.inicio, 'YYYY-MM-DD HH24:MI') AS inicio,
       ROUND(EXTRACT(EPOCH FROM e.fin - e.inicio)::numeric, 1) AS segundos,
       e.parametros ->> 'origen' AS origen,
       SUM(p.filas_cargadas)   AS filas_cargadas,
       SUM(p.filas_rechazadas) AS filas_rechazadas
FROM etl.ejecucion e
LEFT JOIN etl.paso p USING (id_ejecucion)
GROUP BY e.id_ejecucion
ORDER BY e.id_ejecucion DESC
LIMIT 15""",
        },
        {
            "nombre": "Filas rechazadas por motivo",
            "tipo": "row", "ejes": (["motivo"], ["filas"]), "pos": (16, 14, 10, 7),
            "sql": """
SELECT motivo, COUNT(*) AS filas
FROM etl.rechazo
GROUP BY motivo
ORDER BY filas DESC""",
        },
    ],
}

# =====================================================================
#  DASHBOARD 3: RECURSOS HUMANOS (de los Excel de RRHH)
# =====================================================================
ULTIMO_MES_RRHH = "(SELECT MAX(mes) FROM marts.rpt_rrhh_centro_mes)"

RRHH = {
    "nombre": "TechNova - Recursos Humanos",
    "descripcion": "Horas, horas extra, absentismo, coste de personal y productividad, a partir de los Excel de RRHH",
    "tarjetas": [
        # ---------------- KPIs del último mes ----------------
        {
            "nombre": "Plantilla (último mes)",
            "tipo": "scalar", "pos": (0, 0, 6, 3),
            "sql": f"SELECT SUM(plantilla) AS plantilla FROM marts.rpt_rrhh_centro_mes WHERE mes = {ULTIMO_MES_RRHH}",
        },
        {
            "nombre": "Horas extra (último mes)",
            "tipo": "scalar", "pos": (0, 6, 6, 3),
            "sql": f"SELECT ROUND(SUM(horas_extra)) AS horas_extra FROM marts.rpt_rrhh_centro_mes WHERE mes = {ULTIMO_MES_RRHH}",
        },
        {
            "nombre": "Absentismo (último mes)",
            "tipo": "scalar", "porcentaje": ["absentismo"], "pos": (0, 12, 6, 3),
            "sql": f"""
SELECT ROUND(SUM(dias_baja)::numeric / NULLIF(SUM(plantilla * l.dias), 0), 4) AS absentismo
FROM marts.rpt_rrhh_centro_mes r
CROSS JOIN (SELECT COUNT(*) AS dias FROM marts.dim_fecha
            WHERE es_laborable AND date_trunc('month', fecha) = {ULTIMO_MES_RRHH}) l
WHERE r.mes = {ULTIMO_MES_RRHH}""",
        },
        {
            "nombre": "Coste de personal (último mes)",
            "tipo": "scalar", "euros": ["coste"], "pos": (0, 18, 6, 3),
            "sql": f"SELECT ROUND(SUM(coste_personal)) AS coste FROM marts.rpt_rrhh_centro_mes WHERE mes = {ULTIMO_MES_RRHH}",
        },
        # ---------------- Evolución ----------------
        {
            "nombre": "Horas extra por mes y tipo de centro",
            "tipo": "bar", "ejes": (["mes", "tipo"], ["horas_extra"]), "pos": (3, 0, 12, 7),
            "sql": """
SELECT to_char(mes, 'YYYY-MM') AS mes, tipo, ROUND(SUM(horas_extra)) AS horas_extra
FROM marts.rpt_rrhh_centro_mes
GROUP BY mes, tipo
ORDER BY mes, tipo""",
        },
        {
            "nombre": "Coste de personal mensual",
            "tipo": "line", "ejes": (["mes"], ["coste"]), "euros": ["coste"], "pos": (3, 12, 12, 7),
            "sql": """
SELECT to_char(mes, 'YYYY-MM') AS mes, ROUND(SUM(coste_personal)) AS coste
FROM marts.rpt_rrhh_centro_mes
GROUP BY mes
ORDER BY mes""",
        },
        # ---------------- Centros ----------------
        {
            "nombre": "Absentismo por centro (último año)",
            "tipo": "row", "ejes": (["centro"], ["absentismo"]), "porcentaje": ["absentismo"], "pos": (10, 0, 12, 7),
            "sql": """
SELECT centro, ROUND(SUM(dias_baja)::numeric / NULLIF(SUM(plantilla * l.dias), 0), 4) AS absentismo
FROM marts.rpt_rrhh_centro_mes r
JOIN (SELECT date_trunc('month', fecha)::date AS mes, COUNT(*) AS dias
      FROM marts.dim_fecha WHERE es_laborable GROUP BY 1) l USING (mes)
WHERE r.mes > (SELECT MAX(mes) FROM marts.rpt_rrhh_centro_mes) - INTERVAL '12 months'
GROUP BY centro
ORDER BY absentismo DESC""",
        },
        {
            "nombre": "Ventas por hora trabajada por tienda (último año)",
            "tipo": "row", "ejes": (["tienda"], ["ventas_por_hora"]), "euros": ["ventas_por_hora"],
            "pos": (10, 12, 12, 7),
            "sql": """
SELECT tienda, ROUND(SUM(ventas) / NULLIF(SUM(horas), 0), 2) AS ventas_por_hora
FROM marts.rpt_productividad_vendedor
WHERE mes > (SELECT MAX(mes) FROM marts.rpt_productividad_vendedor) - INTERVAL '12 months'
GROUP BY tienda
ORDER BY ventas_por_hora DESC""",
        },
        {
            "nombre": "Días de ausencia por tipo (último año)",
            "tipo": "pie", "ejes": (["tipo"], ["dias"]), "pos": (17, 0, 8, 7),
            "sql": """
SELECT INITCAP(REPLACE(tipo, '_', ' ')) AS tipo, COUNT(*) AS dias
FROM marts.fct_ausencias
WHERE fecha > (SELECT MAX(fecha) FROM marts.fct_ausencias) - INTERVAL '12 months'
GROUP BY tipo
ORDER BY dias DESC""",
        },
        {
            "nombre": "Top 10 vendedores por ventas por hora (último año)",
            "tipo": "table", "euros": ["ventas", "ventas_por_hora"], "pos": (17, 8, 16, 7),
            "sql": """
SELECT empleado, tienda,
       ROUND(SUM(horas))                                   AS horas,
       ROUND(SUM(ventas))                                  AS ventas,
       ROUND(SUM(ventas) / NULLIF(SUM(horas), 0), 2)       AS ventas_por_hora,
       ROUND(SUM(ventas) / NULLIF(SUM(coste_total), 0), 2) AS ventas_por_euro_coste
FROM marts.rpt_productividad_vendedor
WHERE mes > (SELECT MAX(mes) FROM marts.rpt_productividad_vendedor) - INTERVAL '12 months'
GROUP BY empleado, tienda
HAVING SUM(horas) > 100
ORDER BY ventas_por_hora DESC
LIMIT 10""",
        },
    ],
}

# =====================================================================
#  MACHINE LEARNING (Fase 8): lee los resultados del esquema ml
# =====================================================================
ML = {
    "nombre": "TechNova - Machine Learning",
    "descripcion": "Segmentación de clientes con K-Means y previsión de ventas a 3 meses (se reentrenan cada mes)",
    "tarjetas": [
        # ---------------- KPIs ----------------
        {
            "nombre": "Clientes segmentados",
            "tipo": "scalar", "pos": (0, 0, 6, 3),
            "sql": "SELECT COUNT(*) AS clientes FROM ml.segmento_cliente",
        },
        {
            "nombre": "Gasto que concentra el segmento más valioso",
            "tipo": "scalar", "porcentaje": ["pct_gasto"], "pos": (0, 6, 6, 3),
            "sql": "SELECT pct_gasto FROM ml.segmento_resumen ORDER BY gasto_total DESC LIMIT 1",
        },
        {
            "nombre": "Ventas previstas próximos 3 meses",
            "tipo": "scalar", "euros": ["prevision"], "pos": (0, 12, 6, 3),
            "sql": "SELECT ROUND(SUM(prevision)) AS prevision FROM ml.prevision_ventas",
        },
        {
            "nombre": "Error mensual del modelo en el backtest",
            "tipo": "scalar", "porcentaje": ["error_mensual"], "pos": (0, 18, 6, 3),
            "sql": """
SELECT ROUND(AVG(error_mensual), 4) AS error_mensual
FROM ml.metricas_prevision WHERE elegido""",
        },
        # ---------------- Segmentación ----------------
        {
            "nombre": "Clientes por segmento (K-Means)",
            "tipo": "pie", "ejes": (["segmento"], ["clientes"]), "pos": (3, 0, 8, 7),
            "sql": "SELECT segmento, clientes FROM ml.segmento_resumen ORDER BY clientes DESC",
        },
        {
            "nombre": "Gasto por segmento",
            "tipo": "row", "ejes": (["segmento"], ["gasto_total"]), "euros": ["gasto_total"], "pos": (3, 8, 8, 7),
            "sql": "SELECT segmento, gasto_total FROM ml.segmento_resumen ORDER BY gasto_total DESC",
        },
        {
            "nombre": "Ticket medio por segmento",
            "tipo": "bar", "ejes": (["segmento"], ["ticket_medio"]), "euros": ["ticket_medio"], "pos": (3, 16, 8, 7),
            "sql": "SELECT segmento, ticket_medio FROM ml.segmento_resumen ORDER BY gasto_total DESC",
        },
        {
            "nombre": "Perfil y acción recomendada por segmento",
            "tipo": "table", "euros": ["gasto_medio", "ticket_medio"], "porcentaje": ["pct_clientes", "pct_web"],
            "pos": (10, 0, 24, 6),
            "sql": """
SELECT segmento, clientes, pct_clientes, ROUND(recencia_media) AS dias_sin_comprar,
       pedidos_medio, gasto_medio, ticket_medio, pct_web, descripcion, accion
FROM ml.segmento_resumen
ORDER BY gasto_total DESC""",
        },
        {
            "nombre": "Segmentos K-Means frente a segmentos RFM",
            "tipo": "bar", "ejes": (["segmento", "segmento_rfm"], ["clientes"]), "pos": (16, 0, 24, 7),
            "sql": """
SELECT segmento, segmento_rfm, COUNT(*) AS clientes
FROM ml.segmento_cliente
GROUP BY segmento, segmento_rfm
ORDER BY segmento, segmento_rfm""",
        },
        # ---------------- Previsión ----------------
        {
            "nombre": "Ventas mensuales: real y previsión",
            "tipo": "bar", "ejes": (["mes", "serie"], ["ventas"]), "euros": ["ventas"], "pos": (23, 0, 24, 7),
            "sql": """
SELECT to_char(date_trunc('month', dia), 'YYYY-MM') AS mes, 'Real' AS serie, ROUND(SUM(importe_neto)) AS ventas
FROM marts.fct_ventas
WHERE dia > (SELECT MAX(dia) FROM marts.fct_ventas) - INTERVAL '12 months'
GROUP BY 1
UNION ALL
SELECT to_char(date_trunc('month', fecha), 'YYYY-MM'), 'Previsión', ROUND(SUM(prevision))
FROM ml.prevision_ventas
GROUP BY 1
ORDER BY 1, 2""",
        },
        {
            "nombre": "Previsión diaria con intervalo del 80 %",
            "tipo": "line", "ejes": (["fecha"], ["prevision", "limite_inferior", "limite_superior"]),
            "euros": ["prevision", "limite_inferior", "limite_superior"], "pos": (30, 0, 24, 7),
            "sql": """
SELECT fecha, SUM(prevision) AS prevision, SUM(limite_inferior) AS limite_inferior,
       SUM(limite_superior) AS limite_superior
FROM ml.prevision_ventas
GROUP BY fecha
ORDER BY fecha""",
        },
        {
            "nombre": "Backtest: ventas semanales reales y previstas (último trimestre)",
            "tipo": "line", "ejes": (["semana"], ["real", "combinado", "gradient_boosting", "anio_anterior",
                                                  "media_4_semanas"]),
            "euros": ["real", "combinado", "gradient_boosting", "anio_anterior", "media_4_semanas"],
            "pos": (37, 0, 14, 7),
            "sql": """
SELECT date_trunc('week', fecha)::date AS semana, ROUND(SUM(real)) AS real, ROUND(SUM(combinado)) AS combinado,
       ROUND(SUM(gradient_boosting)) AS gradient_boosting, ROUND(SUM(anio_anterior)) AS anio_anterior,
       ROUND(SUM(media_4_semanas)) AS media_4_semanas
FROM ml.backtest_ventas
GROUP BY 1
ORDER BY 1""",
        },
        {
            "nombre": "Comparativa de modelos de previsión",
            "tipo": "table", "porcentaje": ["wape", "error_mensual", "sesgo"], "pos": (37, 14, 10, 7),
            "sql": """
SELECT canal, modelo, wape, error_mensual, sesgo,
       CASE WHEN elegido THEN 'Elegido' ELSE '' END AS elegido
FROM ml.metricas_prevision
ORDER BY canal, wape""",
        },
    ],
}

DASHBOARDS = [VENTAS, OPERACIONES, RRHH, ML]