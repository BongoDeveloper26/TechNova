"""
seed_postventa.py -> Fase 2.5a: devoluciones, reembolsos y garantías.

Reglas de negocio simuladas:
  - Derecho de desistimiento: 14 días desde la entrega para devolver.
    Si el producto es defectuoso, hasta 30 días.
  - En la web se devuelve más que en tienda (no puedes probar el producto).
  - Cada devolución reembolsada genera un pago en estado 'reembolsado'.
  - Si se devuelve TODO el pedido, su estado pasa a 'devuelto'.
  - Garantía: averías desde el día 31 hasta los 36 meses (garantía legal en España).

Requiere haber ejecutado antes seed_ventas.py.
"""
import random
from datetime import datetime, timedelta

from config import FECHA_FIN, SEMILLA
from db import get_connection
from seed_ventas import actualizar_fidelidad

LIMITE = datetime.combine(FECHA_FIN, datetime.max.time())

# Probabilidad base de devolver una línea, según subcategoría
PROB_DEVOLUCION = {
    "Auriculares": 0.08, "Accesorios móvil": 0.07, "Smartwatches": 0.07,
    "Smartphones": 0.06, "Portátiles": 0.05, "Sillas gaming": 0.06,
    "Videojuegos": 0.02, "Componentes": 0.03,
}
PROB_DEVOLUCION_DEFECTO = 0.04
FACTOR_CANAL = {"web": 1.6, "tienda": 0.7}

MOTIVOS = {
    "web": (["no_es_lo_esperado", "defectuoso", "error_pedido", "llego_tarde", "otro"],
            [40, 20, 15, 12, 13]),
    "tienda": (["no_es_lo_esperado", "defectuoso", "error_pedido", "otro"],
               [45, 30, 10, 15]),
}

# Probabilidad de avería en garantía, según subcategoría
PROB_GARANTIA = {
    "Portátiles": 0.03, "Smartphones": 0.03, "Robots aspiradores": 0.035, "Consolas": 0.025,
    "Televisores": 0.02, "Videojuegos": 0.002, "Accesorios móvil": 0.005,
}
PROB_GARANTIA_DEFECTO = 0.015

PROBLEMAS = {
    "Informática": ["No enciende", "Pantalla con píxeles muertos", "Batería no carga",
                    "Teclado no responde", "Se apaga solo por sobrecalentamiento"],
    "Telefonía": ["Batería se agota muy rápido", "Pantalla táctil no responde",
                  "No carga por USB-C", "Fallo en la cámara", "Se reinicia solo"],
    "Imagen y sonido": ["Pantalla con líneas", "No emite sonido", "Fallo de conexión Bluetooth",
                        "Mando a distancia no funciona", "Un auricular no se oye"],
    "Gaming": ["El mando tiene drift", "No lee discos", "Se apaga en mitad de partida",
               "Reposabrazos roto", "Ventilador muy ruidoso"],
    "Hogar inteligente": ["No conecta al WiFi", "No carga en la base", "Motor bloqueado",
                          "La app no detecta el dispositivo", "Deja de calentar"],
}


def cargar_lineas_entregadas(cur):
    cur.execute("""
        SELECT l.id_linea, l.id_pedido, l.cantidad, l.precio_unitario, l.descuento,
               pe.canal, COALESCE(e.fecha_entrega, pe.fecha) AS fecha_base,
               hija.nombre AS subcategoria, padre.nombre AS categoria,
               pa.metodo AS metodo_pago
        FROM linea_pedido l
        JOIN pedido pe        ON pe.id_pedido = l.id_pedido
        LEFT JOIN envio e     ON e.id_pedido = pe.id_pedido
        JOIN pago pa          ON pa.id_pedido = pe.id_pedido AND pa.estado = 'completado'
        JOIN producto p       ON p.id_producto = l.id_producto
        JOIN categoria hija   ON hija.id_categoria = p.id_categoria
        JOIN categoria padre  ON padre.id_categoria = hija.id_categoria_padre
        WHERE pe.estado = 'entregado'
        ORDER BY l.id_linea
    """)
    return cur.fetchall()


def generar_devoluciones(lineas):
    devoluciones, reembolsos, lineas_devueltas = [], [], set()

    for (id_linea, id_pedido, cantidad, precio, descuento, canal,
         fecha_base, subcat, _, metodo) in lineas:
        prob = PROB_DEVOLUCION.get(subcat, PROB_DEVOLUCION_DEFECTO) * FACTOR_CANAL[canal]
        if random.random() >= prob:
            continue

        motivo = random.choices(*MOTIVOS[canal])[0]
        dias_max = 30 if motivo == "defectuoso" else 14
        fecha = fecha_base + timedelta(days=random.randint(1, dias_max), hours=random.randint(0, 10))
        if fecha > LIMITE:
            continue

        unidades = random.randint(1, cantidad)
        precio_neto_unidad = (float(precio) * cantidad - float(descuento)) / cantidad
        importe = round(precio_neto_unidad * unidades, 2)

        if fecha > LIMITE - timedelta(days=5):
            estado = "solicitada"                       # todavía sin resolver
        else:
            estado = random.choices(["reembolsada", "rechazada", "aceptada"], weights=[85, 10, 5])[0]
        reembolso = importe if estado in ("reembolsada", "aceptada") else None

        devoluciones.append((id_linea, unidades, motivo, fecha, estado, reembolso))
        lineas_devueltas.add(id_linea)

        if estado == "reembolsada" and importe > 0:
            fecha_reembolso = fecha + timedelta(days=random.randint(3, 7))
            if fecha_reembolso <= LIMITE:
                reembolsos.append((id_pedido, metodo or "tarjeta", importe, fecha_reembolso, "reembolsado"))

    return devoluciones, reembolsos, lineas_devueltas


def generar_garantias(lineas, lineas_devueltas):
    garantias = []
    for id_linea, _, _, _, _, _, fecha_base, subcat, categoria, _ in lineas:
        if id_linea in lineas_devueltas:
            continue
        if random.random() >= PROB_GARANTIA.get(subcat, PROB_GARANTIA_DEFECTO):
            continue

        fecha = (fecha_base + timedelta(days=random.randint(31, 36 * 30))).date()
        if fecha > FECHA_FIN:
            continue

        if (FECHA_FIN - fecha).days < 30:
            estado = random.choice(["abierta", "en_reparacion"])
        else:
            estado = random.choices(["reparado", "sustituido", "rechazada"], weights=[55, 25, 20])[0]
        garantias.append((id_linea, fecha, random.choice(PROBLEMAS[categoria]), estado))
    return garantias


def main():
    random.seed(SEMILLA)

    with get_connection() as conn, conn.cursor() as cur:
        # Idempotencia: deshacemos lo que creó una ejecución anterior
        cur.execute("TRUNCATE devolucion, garantia RESTART IDENTITY")
        cur.execute("DELETE FROM pago WHERE estado = 'reembolsado'")
        cur.execute("UPDATE pedido SET estado = 'entregado' WHERE estado = 'devuelto'")

        lineas = cargar_lineas_entregadas(cur)
        devoluciones, reembolsos, lineas_devueltas = generar_devoluciones(lineas)
        garantias = generar_garantias(lineas, lineas_devueltas)

        cur.executemany(
            """INSERT INTO devolucion (id_linea, cantidad, motivo, fecha, estado, importe_reembolso)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            devoluciones,
        )
        cur.executemany(
            "INSERT INTO pago (id_pedido, metodo, importe, fecha, estado) VALUES (%s, %s, %s, %s, %s)",
            reembolsos,
        )
        cur.executemany(
            "INSERT INTO garantia (id_linea, fecha_reclamacion, problema, estado) VALUES (%s, %s, %s, %s)",
            garantias,
        )

        # Pedido 'devuelto' = TODAS sus líneas se han devuelto enteras y reembolsado
        cur.execute("""
            WITH devuelto_por_linea AS (
                SELECT id_linea, SUM(cantidad) AS uds
                FROM devolucion
                WHERE estado = 'reembolsada'
                GROUP BY id_linea
            ),
            pedidos_completos AS (
                SELECT l.id_pedido
                FROM linea_pedido l
                LEFT JOIN devuelto_por_linea d ON d.id_linea = l.id_linea
                GROUP BY l.id_pedido
                HAVING BOOL_AND(l.cantidad <= COALESCE(d.uds, 0))   -- TODAS las líneas devueltas
            )
            UPDATE pedido pe
            SET estado = 'devuelto'
            FROM pedidos_completos pc
            WHERE pe.id_pedido = pc.id_pedido AND pe.estado = 'entregado'
        """)
        pedidos_devueltos = cur.rowcount

        actualizar_fidelidad(cur)  # los reembolsos restan puntos

        print("\n📊 Filas cargadas:")
        print(f"   devolucion          {len(devoluciones):>6}")
        print(f"   pago (reembolsos)   {len(reembolsos):>6}")
        print(f"   garantia            {len(garantias):>6}")
        print(f"   pedidos devueltos   {pedidos_devueltos:>6}")

    print("\n✅ Postventa generada")


if __name__ == "__main__":
    main()