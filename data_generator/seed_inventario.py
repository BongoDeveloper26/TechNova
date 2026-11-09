"""
seed_inventario.py -> Fase 2.5b: compras a proveedores y stock.

Simula cómo repone TechNova sus almacenes mes a mes:
  1. Cada mes, cada almacén calcula cuánto va a vender el mes siguiente
     (una previsión con error, como en la vida real).
  2. Pide a cada proveedor lo que le falta para llegar a esa previsión
     + un 15 % de stock de seguridad.
  3. Los proveedores de fuera de la UE tardan más y cobran en su moneda
     (USD, JPY, GBP), así que guardamos el tipo de cambio del momento.
  4. Al final queda una "foto" del stock en almacenes y tiendas.

Requiere haber ejecutado antes seed_ventas.py.
"""
import math
import random
from collections import defaultdict
from datetime import date, datetime, timedelta

from config import FECHA_FIN, FECHA_INICIO, SEMILLA
from db import get_connection
from seed_ventas import ALMACEN_POR_PROVINCIA

# Qué proveedor sirve cada marca
PROVEEDOR_POR_MARCA = {
    "Cecotec": "Iberia Tech Distribución S.L.", "Xiaomi": "Iberia Tech Distribución S.L.",
    "Lenovo": "Iberia Tech Distribución S.L.", "HP": "Iberia Tech Distribución S.L.",
    "Logitech": "EuroGadget Wholesale GmbH", "Bose": "EuroGadget Wholesale GmbH",
    "JBL": "EuroGadget Wholesale GmbH", "Garmin": "EuroGadget Wholesale GmbH",
    "Microsoft": "EuroGadget Wholesale GmbH",
    "ASUS": "Pacific Electronics Supply Ltd.", "MSI": "Pacific Electronics Supply Ltd.",
    "Acer": "Pacific Electronics Supply Ltd.", "Roborock": "Pacific Electronics Supply Ltd.",
    "Samsung": "Pacific Electronics Supply Ltd.", "LG": "Pacific Electronics Supply Ltd.",
    "Apple": "Atlantic Devices Inc.", "Dell": "Atlantic Devices Inc.",
    "Sony": "Nippon Digital Trading K.K.", "Nintendo": "Nippon Digital Trading K.K.",
    "Dyson": "Albion Tech Distribution Ltd.",
}

# Días que tarda en llegar la mercancía según la moneda (≈ origen)
PLAZO_ENTREGA = {"EUR": (3, 7), "GBP": (5, 10), "USD": (14, 30), "JPY": (18, 32)}

# Tipo de cambio aproximado (unidades de moneda por 1 €) al inicio y al final del periodo.
# ⚠️ Son valores simulados: en la Fase 4 los sustituiremos por los reales usando una API.
TIPO_CAMBIO = {"USD": (1.07, 1.17), "JPY": (145.0, 172.0), "GBP": (0.86, 0.86), "EUR": (1.0, 1.0)}


def tipo_cambio(moneda, dia):
    inicio, fin = TIPO_CAMBIO[moneda]
    if moneda == "EUR":
        return 1.0
    avance = (dia - FECHA_INICIO).days / (FECHA_FIN - FECHA_INICIO).days
    avance = min(max(avance, 0), 1)
    return round((inicio + (fin - inicio) * avance) * random.uniform(0.985, 1.015), 6)


def meses(desde: date, hasta: date):
    actual = date(desde.year, desde.month, 1)
    while actual <= hasta:
        yield actual
        actual = date(actual.year + (actual.month == 12), actual.month % 12 + 1, 1)


def mes_anterior(mes: date) -> date:
    return date(mes.year - (mes.month == 1), (mes.month - 2) % 12 + 1, 1)


def cargar_contexto(cur):
    ctx = {}
    cur.execute("SELECT nombre, id_proveedor, moneda FROM proveedor")
    ctx["proveedores"] = {n: (i, m) for n, i, m in cur.fetchall()}

    cur.execute("""
        SELECT p.id_producto, m.nombre, p.coste
        FROM producto p JOIN marca m USING (id_marca)
    """)
    ctx["productos"] = {pid: (PROVEEDOR_POR_MARCA[marca], float(coste)) for pid, marca, coste in cur.fetchall()}

    # ¿Qué almacén abastece a cada tienda? (misma regla que los envíos web)
    cur.execute("""
        SELECT u.id_ubicacion, u.nombre, u.tipo, c.provincia
        FROM ubicacion u JOIN ciudad c USING (id_ciudad)
    """)
    filas = cur.fetchall()
    almacenes = {nombre: uid for uid, nombre, tipo, _ in filas if tipo == "almacen"}
    ctx["almacenes"] = list(almacenes.values())
    ctx["almacen_de"] = {
        uid: almacenes[ALMACEN_POR_PROVINCIA.get(prov, "Almacén Central Getafe")]
        for uid, _, tipo, prov in filas if tipo == "tienda"
    }
    for uid in ctx["almacenes"]:
        ctx["almacen_de"][uid] = uid  # los pedidos web ya traen su almacén

    # Unidades vendidas por (mes, almacén, producto) y por (tienda, producto) en el último trimestre
    cur.execute("""
        SELECT date_trunc('month', pe.fecha)::date, pe.canal, pe.id_ubicacion,
               l.id_producto, SUM(l.cantidad)::int
        FROM pedido pe JOIN linea_pedido l USING (id_pedido)
        WHERE pe.estado <> 'cancelado'
        GROUP BY 1, 2, 3, 4
    """)
    ctx["demanda"] = defaultdict(int)
    ctx["ventas_tienda_trimestre"] = defaultdict(int)
    inicio_trimestre = date(FECHA_FIN.year, FECHA_FIN.month, 1) - timedelta(days=62)
    for mes, canal, id_ubi, id_prod, unidades in cur.fetchall():
        ctx["demanda"][(mes, ctx["almacen_de"][id_ubi], id_prod)] += unidades
        if canal == "tienda" and mes >= inicio_trimestre:
            ctx["ventas_tienda_trimestre"][(id_ubi, id_prod)] += unidades
    return ctx


def simular_compras(ctx):
    pedidos_compra, lineas_compra = [], []
    stock = defaultdict(int)                       # (almacén, producto) -> unidades
    demanda_por_mes = defaultdict(dict)            # mes -> {(almacén, producto): unidades}
    for (mes, almacen, prod), uds in ctx["demanda"].items():
        demanda_por_mes[mes][(almacen, prod)] = uds
    total_vendido = defaultdict(int)

    for mes in meses(FECHA_INICIO, FECHA_FIN):
        dia_pedido = mes_anterior(mes) + timedelta(days=9 + random.randint(0, 4))
        demanda = demanda_por_mes.get(mes, {})

        # 1) Qué hay que pedir: previsión (con error) + 15 % de seguridad - stock actual
        por_proveedor = defaultdict(list)          # (proveedor, almacén) -> líneas
        for (almacen, prod), uds in demanda.items():
            prevision = uds * random.uniform(0.85, 1.20)
            a_pedir = math.ceil(prevision * 1.15 - stock[(almacen, prod)])
            if a_pedir > 0:
                proveedor, coste = ctx["productos"][prod]
                por_proveedor[(proveedor, almacen)].append((prod, a_pedir, coste))

        # 2) Un pedido de compra por proveedor y almacén
        for (proveedor, almacen), lineas in sorted(por_proveedor.items()):
            id_proveedor, moneda = ctx["proveedores"][proveedor]
            tc = tipo_cambio(moneda, dia_pedido)
            recepcion = dia_pedido + timedelta(days=random.randint(*PLAZO_ENTREGA[moneda]))

            if random.random() < 0.02:
                estado, recepcion = "cancelado", None
            elif recepcion <= FECHA_FIN:
                estado = "recibido"
            else:
                estado, recepcion = "enviado", None

            idx = len(pedidos_compra)
            pedidos_compra.append((id_proveedor, almacen, dia_pedido, recepcion, estado, tc))
            for prod, cantidad, coste in lineas:
                coste_moneda = round(coste * tc * random.uniform(0.97, 1.03), 2)
                lineas_compra.append((idx, prod, cantidad, coste_moneda))
                if estado == "recibido":
                    stock[(almacen, prod)] += cantidad

        # 3) Se vende lo del mes (si no hay suficiente, rotura de stock -> se queda a 0)
        for (almacen, prod), uds in demanda.items():
            stock[(almacen, prod)] = max(0, stock[(almacen, prod)] - uds)
            total_vendido[(almacen, prod)] += uds

    return pedidos_compra, lineas_compra, stock, total_vendido


def foto_stock(ctx, stock_almacen, total_vendido):
    num_meses = sum(1 for _ in meses(FECHA_INICIO, FECHA_FIN))
    momento = datetime.combine(FECHA_FIN, datetime.min.time()) + timedelta(hours=22)
    filas = []

    for (almacen, prod), cantidad in sorted(stock_almacen.items()):
        media_mensual = total_vendido[(almacen, prod)] / num_meses
        filas.append((prod, almacen, cantidad, max(1, round(media_mensual * 0.5)), momento))

    for (tienda, prod), vendidas in sorted(ctx["ventas_tienda_trimestre"].items()):
        cantidad = random.randint(0, vendidas // 3 + 2)    # producto en exposición
        filas.append((prod, tienda, cantidad, max(1, vendidas // 6), momento))
    return filas


def main():
    random.seed(SEMILLA)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE pedido_compra, stock RESTART IDENTITY CASCADE")
        ctx = cargar_contexto(cur)
        pedidos_compra, lineas_compra, stock_almacen, total_vendido = simular_compras(ctx)

        cur.executemany(
            """INSERT INTO pedido_compra (id_proveedor, id_ubicacion, fecha_pedido,
                                          fecha_recepcion, estado, tipo_cambio)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING id_pedido_compra""",
            pedidos_compra, returning=True,
        )
        ids = []
        while True:
            ids.append(cur.fetchone()[0])
            if not cur.nextset():
                break

        cur.executemany(
            """INSERT INTO linea_compra (id_pedido_compra, id_producto, cantidad, coste_unitario)
               VALUES (%s, %s, %s, %s)""",
            [(ids[i], *resto) for i, *resto in lineas_compra],
        )
        filas_stock = foto_stock(ctx, stock_almacen, total_vendido)
        cur.executemany(
            """INSERT INTO stock (id_producto, id_ubicacion, cantidad, stock_minimo, fecha_actualizacion)
               VALUES (%s, %s, %s, %s, %s)""",
            filas_stock,
        )

        cur.execute("SELECT COUNT(*) FROM stock WHERE cantidad < stock_minimo")
        bajo_minimo = cur.fetchone()[0]
        print("\n📊 Filas cargadas:")
        print(f"   pedido_compra   {len(pedidos_compra):>6}")
        print(f"   linea_compra    {len(lineas_compra):>6}")
        print(f"   stock           {len(filas_stock):>6}  ({bajo_minimo} por debajo del mínimo ⚠️)")

    print("\n✅ Compras y stock generados")


if __name__ == "__main__":
    main()