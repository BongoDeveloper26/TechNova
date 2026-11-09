"""
seed_ventas.py -> Fase 2.4: promociones, cupones, pedidos, líneas, pagos y envíos.

Simula 3 años de ventas DÍA A DÍA, en orden cronológico, con:
  - estacionalidad (rebajas, Black Friday, Navidad, agosto flojo...)
  - más pedidos cuantos más clientes registrados hay (la tienda crece)
  - canal web vs tienda, empleados, pagos fallidos, retrasos en envíos...
  - descuentos por promoción, por cupón y por nivel de fidelidad

Requiere haber ejecutado antes seed_maestros.py y seed_entidades.py.
"""
import bisect
import math
import random
from datetime import date, datetime, timedelta

from config import FECHA_FIN, FECHA_INICIO, PEDIDOS_POR_CLIENTE_ANIO, SEMILLA
from db import get_connection
from seed_entidades import precio_comercial

# ---------------------------------------------------------------------
# 1. CALENDARIO COMERCIAL
# ---------------------------------------------------------------------

FACTOR_MES = {1: 1.15, 2: 0.80, 3: 0.95, 4: 0.90, 5: 0.90, 6: 0.95,
              7: 1.05, 8: 0.75, 9: 1.10, 10: 0.95, 11: 1.20, 12: 1.50}
FACTOR_DIA_SEMANA = [0.90, 0.90, 0.95, 1.00, 1.15, 1.35, 0.75]  # lunes ... domingo

# Horas a las que se compra (pesos de 0h a 23h)
PESO_HORA_WEB = [1, 0.5, 0.3, 0.2, 0.2, 0.3, 0.6, 1, 2, 3, 4, 5,
                 6, 6, 5, 4, 4, 5, 6, 7, 8, 9, 7, 3]
HORAS_TIENDA = list(range(10, 22))
PESO_HORA_TIENDA = [3, 4, 5, 6, 5, 4, 4, 5, 7, 9, 8, 5]

TRANSPORTISTAS = ["SEUR", "Correos Express", "MRW", "GLS", "DHL"]
PESO_TRANSPORTISTA = [30, 25, 20, 15, 10]

# Desde qué almacén se envía según la provincia de destino
ALMACEN_POR_PROVINCIA = {
    "Barcelona": "Almacén Noreste El Prat", "Zaragoza": "Almacén Noreste El Prat",
    "Bizkaia": "Almacén Noreste El Prat", "Illes Balears": "Almacén Noreste El Prat",
    "Valencia": "Almacén Noreste El Prat",
    "Sevilla": "Almacén Sur Sevilla", "Málaga": "Almacén Sur Sevilla",
    "Granada": "Almacén Sur Sevilla", "Murcia": "Almacén Sur Sevilla",
    "Alicante": "Almacén Sur Sevilla",
}  # el resto -> Almacén Central Getafe

DESCATALOGADOS_HASTA = date(2025, 1, 1)  # los productos inactivos dejaron de venderse aquí

# Descuento equivalente a "quitar el IVA": 1 - 1/1.21 = 17,36 %
DESCUENTO_SIN_IVA = 17.36


def black_friday(anio: int) -> date:
    """Black Friday = el día después del 4º jueves de noviembre."""
    primero = date(anio, 11, 1)
    primer_jueves = primero + timedelta(days=(3 - primero.weekday()) % 7)
    return primer_jueves + timedelta(days=22)


def factor_evento(dia: date) -> float:
    """Multiplicador de ventas por eventos especiales."""
    bf = black_friday(dia.year)
    if dia == bf:
        return 5.0
    if dia == bf + timedelta(days=3):                       # Cyber Monday
        return 3.0
    if bf - timedelta(days=7) <= dia <= bf + timedelta(days=3):
        return 2.5                                          # Black Week
    if date(dia.year, 3, 14) <= dia <= date(dia.year, 3, 17):
        return 2.2                                          # Días sin IVA
    if date(dia.year, 12, 15) <= dia <= date(dia.year, 12, 23):
        return 1.4                                          # compras de Navidad
    if (dia.month, dia.day) in [(12, 25), (1, 1), (1, 6)]:
        return 0.3                                          # festivos
    return 1.0


def tiendas_cerradas(dia: date) -> bool:
    return dia.weekday() == 6 or (dia.month, dia.day) in [(12, 25), (1, 1), (1, 6)]


def poisson(lam: float) -> int:
    """Número aleatorio de sucesos con media lam (aproximación normal)."""
    return max(0, round(random.gauss(lam, math.sqrt(lam))))


def momento(dia: date, horas, pesos) -> datetime:
    hora = random.choices(horas, weights=pesos)[0]
    return datetime(dia.year, dia.month, dia.day, hora, random.randint(0, 59), random.randint(0, 59))


# ---------------------------------------------------------------------
# 2. PROMOCIONES Y CUPONES
# ---------------------------------------------------------------------

def crear_promociones(cur):
    """Devuelve (lista de promos automáticas por producto, {año: id_cupon_bienvenida})."""
    cur.execute("""
        SELECT p.id_producto, padre.nombre, hija.nombre
        FROM producto p
        JOIN categoria hija  ON p.id_categoria = hija.id_categoria
        JOIN categoria padre ON hija.id_categoria_padre = padre.id_categoria
    """)
    productos = cur.fetchall()

    def de_categorias(*nombres):
        return {pid for pid, padre, hija in productos if padre in nombres or hija in nombres}

    def al_azar(pct):
        return {pid for pid, _, _ in productos if random.random() < pct}

    promos, cupones = [], {}
    for y in range(FECHA_INICIO.year, FECHA_FIN.year + 1):
        bf = black_friday(y)
        campañas = [
            (f"Rebajas de enero {y}", 15, date(y, 1, 7), date(y, 1, 31), al_azar(0.30)),
            (f"Días sin IVA {y}", DESCUENTO_SIN_IVA, date(y, 3, 14), date(y, 3, 17),
             de_categorias("Imagen y sonido", "Hogar inteligente")),
            (f"Rebajas de verano {y}", 15, date(y, 7, 1), date(y, 7, 31), al_azar(0.30)),
            (f"Vuelta al cole {y}", 10, date(y, 8, 25), date(y, 9, 15),
             de_categorias("Informática", "Smartphones", "Smartwatches")),
            (f"Black Friday {y}", random.choice([20, 25]), bf - timedelta(days=7),
             bf + timedelta(days=3), al_azar(0.60)),
            (f"Navidad {y}", 10, date(y, 12, 1), date(y, 12, 24),
             de_categorias("Gaming", "Imagen y sonido", "Smartwatches")),
        ]
        for nombre, valor, inicio, fin, ids_productos in campañas:
            cur.execute(
                """INSERT INTO promocion (nombre, tipo_descuento, valor, fecha_inicio, fecha_fin)
                   VALUES (%s, 'porcentaje', %s, %s, %s) RETURNING id_promocion""",
                (nombre, valor, inicio, fin),
            )
            id_promo = cur.fetchone()[0]
            cur.executemany(
                "INSERT INTO promocion_producto (id_promocion, id_producto) VALUES (%s, %s)",
                [(id_promo, pid) for pid in ids_productos],
            )
            promos.append((inicio, fin, valor, ids_productos))

        # Cupón de bienvenida: 10 € en el primer pedido web
        cur.execute(
            """INSERT INTO promocion (nombre, tipo_descuento, valor, fecha_inicio, fecha_fin)
               VALUES (%s, 'fijo', 10, %s, %s) RETURNING id_promocion""",
            (f"Bienvenida {y}", date(y, 1, 1), date(y, 12, 31)),
        )
        id_promo = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO cupon (codigo, id_promocion, fecha_caducidad, usos_maximos)
               VALUES (%s, %s, %s, 100000) RETURNING id_cupon""",
            (f"BIENVENIDA{y}", id_promo, date(y, 12, 31)),
        )
        cupones[y] = cur.fetchone()[0]

    return promos, cupones


def descuento_promo(promos, id_producto, dia) -> float:
    """Mayor % de descuento activo para ese producto ese día (si coinciden varias)."""
    return max((valor for inicio, fin, valor, ids in promos
                if inicio <= dia <= fin and id_producto in ids), default=0)


# ---------------------------------------------------------------------
# 3. DATOS DE APOYO (se cargan una vez en memoria)
# ---------------------------------------------------------------------

def cargar_contexto(cur):
    ctx = {}

    # Clientes ordenados por fecha de registro + pesos "80/20"
    # (unos pocos clientes compran muchísimo: distribución de Pareto)
    cur.execute("SELECT id_cliente, fecha_registro::date FROM cliente ORDER BY fecha_registro")
    filas = cur.fetchall()
    ctx["clientes"] = [f[0] for f in filas]
    ctx["registro_clientes"] = [f[1] for f in filas]
    ctx["cum_clientes"] = acumulado(random.paretovariate(1.5) for _ in filas)

    # Productos ordenados por fecha de alta; los baratos se venden más
    cur.execute("SELECT id_producto, precio_venta, activo, fecha_alta FROM producto ORDER BY fecha_alta")
    filas = cur.fetchall()
    ctx["productos"] = [(f[0], float(f[1]), f[2]) for f in filas]
    ctx["alta_productos"] = [f[3] for f in filas]
    ctx["cum_productos"] = acumulado(random.paretovariate(1.2) / float(f[1]) ** 0.8 for f in filas)

    # Direcciones de cada cliente (la principal primero) con su provincia
    cur.execute("""
        SELECT d.id_cliente, d.id_direccion, c.nombre, c.provincia
        FROM direccion d JOIN ciudad c USING (id_ciudad)
        ORDER BY d.id_cliente, d.es_principal DESC
    """)
    ctx["direcciones"] = {}
    for id_cliente, id_dir, ciudad, provincia in cur.fetchall():
        ctx["direcciones"].setdefault(id_cliente, []).append((id_dir, ciudad, provincia))

    # Ubicaciones
    cur.execute("""
        SELECT u.id_ubicacion, u.nombre, u.tipo, c.nombre, u.fecha_apertura
        FROM ubicacion u JOIN ciudad c USING (id_ciudad)
    """)
    ubicaciones = cur.fetchall()
    ctx["tiendas"] = [(u[0], u[3], u[4]) for u in ubicaciones if u[2] == "tienda"]
    ctx["almacenes"] = {u[1]: u[0] for u in ubicaciones if u[2] == "almacen"}

    # Vendedores de cada tienda (con fecha de contratación) y encargados como reserva
    cur.execute("SELECT id_empleado, id_ubicacion, puesto, fecha_contratacion FROM empleado")
    ctx["vendedores"], ctx["encargados"] = {}, {}
    for id_emp, id_ubi, puesto, fecha in cur.fetchall():
        if puesto == "Vendedor":
            ctx["vendedores"].setdefault(id_ubi, []).append((fecha, id_emp))
        elif puesto == "Encargado de tienda":
            ctx["encargados"][id_ubi] = id_emp

    # Niveles de fidelidad (para el descuento según puntos acumulados)
    cur.execute("SELECT puntos_minimos, descuento_pct FROM nivel_fidelidad ORDER BY puntos_minimos")
    ctx["niveles"] = [(p, float(d)) for p, d in cur.fetchall()]
    return ctx


def acumulado(pesos):
    """[2, 1, 3] -> [2, 3, 6]. Permite sortear con pesos usando bisect (muy rápido)."""
    total, resultado = 0.0, []
    for p in pesos:
        total += p
        resultado.append(total)
    return resultado


def sortear(elementos, cum, limite):
    """Elige un elemento con pesos entre los 'limite' primeros."""
    r = random.random() * cum[limite - 1]
    return elementos[bisect.bisect_right(cum, r, 0, limite - 1)]


# ---------------------------------------------------------------------
# 4. SIMULACIÓN DE UN PEDIDO
# ---------------------------------------------------------------------

def elegir_productos(ctx, dia):
    limite = bisect.bisect_right(ctx["alta_productos"], dia)  # solo productos ya lanzados
    num = random.choices([1, 2, 3, 4], weights=[65, 22, 9, 4])[0]
    elegidos = {}
    for _ in range(num * 5):  # varios intentos por si sale repetido o descatalogado
        id_prod, precio, activo = sortear(ctx["productos"], ctx["cum_productos"], limite)
        if id_prod in elegidos or (not activo and dia >= DESCATALOGADOS_HASTA):
            continue
        elegidos[id_prod] = precio
        if len(elegidos) == num:
            break
    return elegidos


def cantidad_para(precio):
    if precio < 30:
        return random.choices([1, 2, 3], weights=[70, 20, 10])[0]
    if precio < 100:
        return random.choices([1, 2], weights=[85, 15])[0]
    return random.choices([1, 2], weights=[98, 2])[0]


def precio_en_fecha(precio_actual, dia):
    """La tecnología baja de precio con el tiempo: antes se vendía ~4 % más cara por año."""
    anios_hasta_hoy = (FECHA_FIN - dia).days / 365
    return precio_comercial(precio_actual * (1 + 0.04 * anios_hasta_hoy))


def descuento_nivel(ctx, puntos):
    pct = 0.0
    for minimo, descuento in ctx["niveles"]:
        if puntos >= minimo:
            pct = descuento
    return pct


def simular_ventas(ctx, promos, cupones):
    pedidos, lineas, pagos, envios = [], [], [], []
    puntos = {}               # puntos acumulados de cada cliente hasta el día actual
    ya_compro_web = set()     # para el cupón de bienvenida

    dia = FECHA_INICIO
    while dia <= FECHA_FIN:
        registrados = bisect.bisect_right(ctx["registro_clientes"], dia)
        lam = (registrados * PEDIDOS_POR_CLIENTE_ANIO / 365
               * FACTOR_MES[dia.month] * FACTOR_DIA_SEMANA[dia.weekday()] * factor_evento(dia))

        # El canal web va ganando peso cada año (45 % -> 60 %)
        prob_web = 0.45 + 0.15 * (dia - FECHA_INICIO).days / (FECHA_FIN - FECHA_INICIO).days
        if tiendas_cerradas(dia):
            prob_web = 1.0

        for _ in range(poisson(lam) if registrados else 0):
            id_cliente = sortear(ctx["clientes"], ctx["cum_clientes"], registrados)
            direcciones = ctx["direcciones"][id_cliente]
            productos = elegir_productos(ctx, dia)
            if not productos:
                continue

            if random.random() < prob_web:
                canal = "web"
                fecha = momento(dia, range(24), PESO_HORA_WEB)
                destino = direcciones[0] if len(direcciones) == 1 or random.random() < 0.8 else direcciones[1]
                almacen = ALMACEN_POR_PROVINCIA.get(destino[2], "Almacén Central Getafe")
                id_ubicacion, id_empleado = ctx["almacenes"][almacen], None
            else:
                canal = "tienda"
                fecha = momento(dia, HORAS_TIENDA, PESO_HORA_TIENDA)
                abiertas = [t for t in ctx["tiendas"] if t[2] <= dia]
                cercanas = [t for t in abiertas if t[1] == direcciones[0][1]]
                tienda = random.choice(cercanas if cercanas and random.random() < 0.75 else abiertas)
                id_ubicacion = tienda[0]
                disponibles = [e for f, e in ctx["vendedores"].get(id_ubicacion, []) if f <= dia]
                id_empleado = random.choice(disponibles) if disponibles else ctx["encargados"][id_ubicacion]

            # --- Líneas del pedido con sus descuentos ---
            pct_nivel = descuento_nivel(ctx, puntos.get(id_cliente, 0))
            lineas_pedido = []
            for id_prod, precio_actual in productos.items():
                precio = precio_en_fecha(precio_actual, dia)
                cantidad = cantidad_para(precio)
                bruto = precio * cantidad
                pct = descuento_promo(promos, id_prod, dia)
                desc = bruto * pct / 100
                desc += (bruto - desc) * pct_nivel / 100      # el nivel se aplica encima
                lineas_pedido.append([id_prod, cantidad, precio, round(desc, 2)])

            # Cupón de bienvenida: 10 € en el primer pedido web de 50 € o más (35 % lo usa)
            id_cupon = None
            subtotal = sum(c * p - d for _, c, p, d in lineas_pedido)
            if (canal == "web" and id_cliente not in ya_compro_web
                    and subtotal >= 50 and random.random() < 0.35):
                id_cupon = cupones[dia.year]
                mas_cara = max(lineas_pedido, key=lambda l: l[1] * l[2] - l[3])
                mas_cara[3] = round(mas_cara[3] + 10, 2)              # se descuenta de la línea más cara
                subtotal -= 10
            if canal == "web":
                ya_compro_web.add(id_cliente)
            total = round(subtotal, 2)

            # --- Pago, envío y estado ---
            idx = len(pedidos)
            cancelado = canal == "web" and random.random() < 0.03

            if canal == "tienda":
                metodo = random.choices(["tarjeta", "efectivo", "financiado"],
                                        weights=[70, 20, 25 if total > 600 else 3])[0]
                pagos.append((idx, metodo, total, fecha, "completado"))
                estado = "entregado"
            else:
                metodo = random.choices(["tarjeta", "paypal", "bizum", "financiado"],
                                        weights=[55, 25, 15, 12 if total > 600 else 2])[0]
                if cancelado or random.random() < 0.04:       # pago rechazado
                    pagos.append((idx, metodo, total, fecha, "fallido"))
                if cancelado:
                    estado = "cancelado"
                else:
                    pagos.append((idx, metodo, total, fecha + timedelta(minutes=random.randint(1, 15)), "completado"))
                    estado, envio = generar_envio(idx, destino, fecha)
                    envios.append(envio)

            if not cancelado:
                puntos[id_cliente] = puntos.get(id_cliente, 0) + int(total)  # 1 punto por euro

            pedidos.append((id_cliente, canal, id_ubicacion, id_empleado, id_cupon, fecha, estado))
            lineas.extend((idx, *linea) for linea in lineas_pedido)

        dia += timedelta(days=1)

    return pedidos, lineas, pagos, envios


def generar_envio(idx, destino, fecha):
    id_direccion, _, provincia = destino
    fecha_envio = fecha + timedelta(hours=random.randint(4, 48))
    dias_transito = random.randint(1, 3)
    if provincia == "Illes Balears":
        dias_transito += 2                                     # envío a las islas
    if fecha.month == 12 or factor_evento(fecha.date()) >= 2.5:
        dias_transito += random.randint(1, 3)                  # saturación en campañas
    fecha_entrega = fecha_envio + timedelta(days=dias_transito, hours=random.randint(0, 8))

    limite = datetime.combine(FECHA_FIN, datetime.max.time())
    if fecha_envio > limite:                                   # aún no ha salido
        return "pagado", (idx, id_direccion, transportista(), None, None, "preparando")
    if fecha_entrega > limite:                                 # está en camino
        return "enviado", (idx, id_direccion, transportista(), fecha_envio, None, "en_transito")
    if random.random() < 0.02:                                 # paquete perdido / dañado
        return "enviado", (idx, id_direccion, transportista(), fecha_envio, None, "incidencia")
    return "entregado", (idx, id_direccion, transportista(), fecha_envio, fecha_entrega, "entregado")


def transportista():
    return random.choices(TRANSPORTISTAS, weights=PESO_TRANSPORTISTA)[0]


# ---------------------------------------------------------------------
# 5. CARGA EN LA BASE DE DATOS
# ---------------------------------------------------------------------

def insertar_ventas(cur, pedidos, lineas, pagos, envios):
    # returning=True -> recuperamos el id que Postgres asigna a cada pedido
    cur.executemany(
        """INSERT INTO pedido (id_cliente, canal, id_ubicacion, id_empleado, id_cupon, fecha, estado)
           VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id_pedido""",
        pedidos, returning=True,
    )
    ids = []
    while True:
        ids.append(cur.fetchone()[0])
        if not cur.nextset():
            break

    # Sustituimos el índice provisional (idx) por el id real del pedido
    cur.executemany(
        """INSERT INTO linea_pedido (id_pedido, id_producto, cantidad, precio_unitario, descuento)
           VALUES (%s, %s, %s, %s, %s)""",
        [(ids[i], *resto) for i, *resto in lineas],
    )
    cur.executemany(
        "INSERT INTO pago (id_pedido, metodo, importe, fecha, estado) VALUES (%s, %s, %s, %s, %s)",
        [(ids[i], *resto) for i, *resto in pagos],
    )
    cur.executemany(
        """INSERT INTO envio (id_pedido, id_direccion, transportista, fecha_envio, fecha_entrega, estado)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        [(ids[i], *resto) for i, *resto in envios],
    )


def actualizar_fidelidad(cur):
    """
    Puntos = 1 por euro pagado, restando lo reembolsado por devoluciones.
    El nivel se calcula a partir de los puntos. Todo en SQL.
    (seed_postventa.py vuelve a llamar a esta función después de crear las devoluciones)
    """
    cur.execute("UPDATE cliente SET puntos = 0")
    cur.execute("""
        UPDATE cliente c
        SET puntos = GREATEST(t.puntos, 0)
        FROM (
            SELECT pe.id_cliente,
                   SUM(CASE pa.estado
                           WHEN 'completado'  THEN  FLOOR(pa.importe)
                           WHEN 'reembolsado' THEN -FLOOR(pa.importe)
                           ELSE 0
                       END)::int AS puntos
            FROM pedido pe
            JOIN pago pa ON pa.id_pedido = pe.id_pedido
            GROUP BY pe.id_cliente
        ) t
        WHERE c.id_cliente = t.id_cliente
    """)
    cur.execute("""
        UPDATE cliente c
        SET id_nivel = (
            SELECT n.id_nivel FROM nivel_fidelidad n
            WHERE n.puntos_minimos <= c.puntos
            ORDER BY n.puntos_minimos DESC
            LIMIT 1
        )
    """)


def mostrar_resumen(cur):
    print("\n📊 Filas cargadas:")
    for tabla in ["promocion", "promocion_producto", "cupon", "pedido", "linea_pedido", "pago", "envio"]:
        cur.execute(f"SELECT COUNT(*) FROM {tabla}")
        print(f"   {tabla:<19} {cur.fetchone()[0]:>7}")

    cur.execute("""
        SELECT EXTRACT(YEAR FROM pe.fecha)::int, COUNT(DISTINCT pe.id_pedido),
               ROUND(SUM(pa.importe))
        FROM pedido pe JOIN pago pa ON pa.id_pedido = pe.id_pedido AND pa.estado = 'completado'
        GROUP BY 1 ORDER BY 1
    """)
    print("\n💶 Facturación por año:")
    for anio, num, importe in cur.fetchall():
        print(f"   {anio}: {num:>6} pedidos  {importe:>12,.0f} €")


# ---------------------------------------------------------------------
# 6. PROGRAMA PRINCIPAL
# ---------------------------------------------------------------------

def main():
    random.seed(SEMILLA)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE pedido, promocion RESTART IDENTITY CASCADE")
        promos, cupones = crear_promociones(cur)
        ctx = cargar_contexto(cur)

        print("⏳ Simulando 3 años de ventas...")
        pedidos, lineas, pagos, envios = simular_ventas(ctx, promos, cupones)

        print("⏳ Guardando en la base de datos...")
        insertar_ventas(cur, pedidos, lineas, pagos, envios)
        actualizar_fidelidad(cur)
        mostrar_resumen(cur)

    print("\n✅ Ventas generadas")


if __name__ == "__main__":
    main()