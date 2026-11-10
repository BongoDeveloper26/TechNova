"""
calidad.py -> Controles de calidad de los datos cargados.

Cada control es una consulta que CUENTA las filas que están mal.
  - 0 filas  -> ok
  - >0 filas -> fallo (con severidad 'error' o 'aviso')

Si algún control de severidad 'error' falla, la ejecución acaba en error
y lo siguiente (dbt, dashboard) no debería ejecutarse con esos datos.
"""
from configuracion import ESTRATEGIAS_OLTP
from registro import log

# (nombre, severidad, descripción, SQL que cuenta las filas incorrectas)
CONTROLES = [
    # Sin este control, unas tablas vacías pasarían todos los demás (nada que esté mal = todo ok)
    ("tablas_clave_vacias", "error",
     "Tablas imprescindibles que han llegado sin ninguna fila",
     """SELECT (NOT EXISTS (SELECT 1 FROM staging.oltp_cliente))::int
             + (NOT EXISTS (SELECT 1 FROM staging.oltp_producto))::int
             + (NOT EXISTS (SELECT 1 FROM staging.oltp_pedido))::int
             + (NOT EXISTS (SELECT 1 FROM staging.oltp_linea_pedido))::int
             + (NOT EXISTS (SELECT 1 FROM staging.oltp_pago))::int
             + (NOT EXISTS (SELECT 1 FROM staging.tipo_cambio))::int"""),

    ("lineas_sin_pedido", "error",
     "Líneas de pedido cuyo pedido no existe en staging (integridad referencial)",
     """SELECT COUNT(*) FROM staging.oltp_linea_pedido l
        WHERE NOT EXISTS (SELECT 1 FROM staging.oltp_pedido p WHERE p.id_pedido = l.id_pedido)"""),

    ("pagos_sin_pedido", "error",
     "Pagos cuyo pedido no existe en staging",
     """SELECT COUNT(*) FROM staging.oltp_pago pa
        WHERE NOT EXISTS (SELECT 1 FROM staging.oltp_pedido p WHERE p.id_pedido = pa.id_pedido)"""),

    ("pedidos_sin_lineas", "aviso",
     "Pedidos sin ninguna línea",
     """SELECT COUNT(*) FROM staging.oltp_pedido p
        WHERE NOT EXISTS (SELECT 1 FROM staging.oltp_linea_pedido l WHERE l.id_pedido = p.id_pedido)"""),

    ("importes_negativos", "error",
     "Líneas con precio o cantidad negativos, o descuento mayor que el importe",
     """SELECT COUNT(*) FROM staging.oltp_linea_pedido
        WHERE precio_unitario < 0 OR cantidad <= 0 OR descuento > precio_unitario * cantidad"""),

    ("stock_negativo", "error",
     "Stock negativo",
     "SELECT COUNT(*) FROM staging.oltp_stock WHERE cantidad < 0"),

    ("tipo_cambio_huecos", "error",
     "Días sin tipo de cambio entre el primero y el último cargado",
     """WITH rango AS (SELECT moneda, MIN(fecha) AS desde, MAX(fecha) AS hasta
                       FROM staging.tipo_cambio GROUP BY moneda)
        SELECT COUNT(*) FROM rango r
        CROSS JOIN LATERAL generate_series(r.desde, r.hasta, INTERVAL '1 day') AS d(dia)
        WHERE NOT EXISTS (SELECT 1 FROM staging.tipo_cambio t
                          WHERE t.moneda = r.moneda AND t.fecha = d.dia::date)"""),

    ("tipo_cambio_desactualizado", "aviso",
     "Monedas cuyo último tipo de cambio real tiene más de 5 días respecto a la fecha de proceso",
     """SELECT COUNT(*) FROM (
            SELECT moneda FROM staging.tipo_cambio
            WHERE moneda <> 'EUR' AND NOT es_interpolado
            GROUP BY moneda
            HAVING MAX(fecha) < %(fecha)s::date - 5) t"""),

    ("proveedores_sin_tarifa", "aviso",
     "Proveedores que no han enviado tarifa para la fecha de proceso",
     """SELECT COUNT(*) FROM staging.oltp_proveedor p
        WHERE NOT EXISTS (SELECT 1 FROM staging.proveedor_tarifa t
                          WHERE t.id_proveedor = p.id_proveedor AND t.fecha_tarifa = %(fecha)s)"""),

    ("tarifa_desviada", "aviso",
     "Tarifas de proveedor que se desvían más de un 30 % del coste del producto",
     """SELECT COUNT(*) FROM staging.proveedor_tarifa t
        JOIN staging.oltp_producto p ON p.sku = t.sku
        WHERE t.fecha_tarifa = %(fecha)s
          AND ABS(t.precio_coste_eur / p.coste - 1) > 0.30"""),
]


def reconciliar_conteos(conn_oltp, conn_dw):
    """Para las tablas de carga completa, el nº de filas debe coincidir con la OLTP."""
    diferencias = []
    for tabla, estrategia in ESTRATEGIAS_OLTP.items():
        if estrategia["tipo"] != "completa":
            continue
        origen = conn_oltp.execute(f"SELECT COUNT(*) FROM oltp.{tabla}").fetchone()[0]
        destino = conn_dw.execute(f"SELECT COUNT(*) FROM staging.oltp_{tabla}").fetchone()[0]
        if origen != destino:
            diferencias.append(f"{tabla}: OLTP {origen} / staging {destino}")
    return diferencias


def guardar(conn_dw, id_ejecucion, nombre, severidad, afectadas, descripcion):
    resultado = "ok" if afectadas == 0 else "fallo"
    conn_dw.execute(
        """INSERT INTO etl.control_calidad (id_ejecucion, nombre, severidad, filas_afectadas,
                                            resultado, descripcion)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (id_ejecucion, nombre, severidad, afectadas, resultado, descripcion),
    )
    return resultado


def ejecutar(conn_oltp, conn_dw, id_ejecucion, fecha_proceso, resultado):
    fallos_error = 0

    for nombre, severidad, descripcion, consulta in CONTROLES:
        afectadas = conn_dw.execute(consulta, {"fecha": fecha_proceso}).fetchone()[0]
        estado = guardar(conn_dw, id_ejecucion, nombre, severidad, afectadas, descripcion)
        marca = "OK   " if estado == "ok" else ("FALLO" if severidad == "error" else "AVISO")
        log.info(f"   [{marca}] {nombre:<28} {afectadas:>6} filas")
        resultado.leidas += 1
        if estado == "fallo":
            if severidad == "error":
                fallos_error += 1
            else:
                resultado.aviso(f"   Aviso de calidad: {nombre} ({afectadas} filas)")

    diferencias = reconciliar_conteos(conn_oltp, conn_dw)
    guardar(conn_dw, id_ejecucion, "reconciliacion_conteos", "error", len(diferencias),
            "Nº de filas de las tablas de carga completa igual en OLTP y staging")
    log.info(f"   [{'OK   ' if not diferencias else 'FALLO'}] {'reconciliacion_conteos':<28} "
             f"{len(diferencias):>6} tablas")
    resultado.leidas += 1
    fallos_error += bool(diferencias)
    for diferencia in diferencias:
        resultado.detalle.append(diferencia)

    resultado.cargadas = len(CONTROLES) + 1 - fallos_error
    if fallos_error:
        resultado.estado = "error"
        resultado.detalle.append(f"{fallos_error} controles de calidad con severidad 'error' han fallado")