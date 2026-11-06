"""
seed_entidades.py -> Fase 2.3: productos, clientes (con direcciones) y empleados.

Requiere haber ejecutado antes seed_maestros.py.
Se puede ejecutar varias veces: vacía sus tablas y las vuelve a generar.
"""
import random
import unicodedata
from datetime import date, timedelta

from faker import Faker

from config import FECHA_FIN, FECHA_INICIO, NUM_CLIENTES, SEMILLA
from db import get_connection

fake = Faker("es_ES")  # nombres, calles, etc. en español

# ---------------------------------------------------------------------
# 1. CATÁLOGO
#    subcategoría -> (rango de precio, rango de margen, [(marca, [líneas])], [variantes])
#    Las variantes van de "menor" a "mayor": cada una sube un poco el precio.
# ---------------------------------------------------------------------
CATALOGO = {
    "Portátiles": ((449, 2999), (0.12, 0.25), [
        ("Apple", ["MacBook Air", "MacBook Pro"]),
        ("Lenovo", ["IdeaPad Slim 5", "ThinkPad E14", "Legion 5", "Yoga 7"]),
        ("HP", ["Pavilion", "Victus 15", "EliteBook 840", "Envy x360"]),
        ("ASUS", ["VivoBook 15", "ZenBook 14", "ROG Strix G16", "TUF Gaming A15"]),
        ("MSI", ["Katana 15", "Stealth 16", "Modern 14"]),
        ("Dell", ["Inspiron 15", "XPS 13", "Latitude 5440"]),
        ("Acer", ["Aspire 5", "Swift Go 14", "Nitro V 15"]),
    ], ["8GB 256GB", "16GB 512GB", "16GB 1TB", "32GB 1TB"]),
    "Ordenadores de sobremesa": ((549, 2499), (0.12, 0.22), [
        ("Apple", ["iMac 24", "Mac mini"]),
        ("HP", ["Pavilion Desktop", "OMEN 25L"]),
        ("Lenovo", ["IdeaCentre 5", "Legion Tower 5"]),
        ("MSI", ["MAG Infinite S3"]),
        ("Dell", ["OptiPlex 7010"]),
        ("ASUS", ["ROG Strix G13"]),
    ], ["i5 16GB 512GB", "Ryzen 7 16GB 1TB", "i7 32GB 1TB"]),
    "Monitores": ((109, 899), (0.18, 0.30), [
        ("Samsung", ["Odyssey G5", "ViewFinity S6"]),
        ("LG", ["UltraGear", "UltraFine"]),
        ("ASUS", ["TUF Gaming VG", "ProArt PA"]),
        ("MSI", ["MAG Optix"]),
        ("Dell", ["UltraSharp U"]),
        ("Acer", ["Nitro XV"]),
    ], ['24" FHD', '27" QHD', '27" 4K', '34" Ultrawide']),
    "Componentes": ((49, 1199), (0.10, 0.22), [
        ("ASUS", ["TUF Gaming RTX 4060", "ROG Strix RTX 4070", "Prime B650-PLUS"]),
        ("MSI", ["GeForce RTX 4070 SUPER Ventus", "MAG B760 Tomahawk", "MAG A750GL Fuente"]),
        ("Samsung", ["SSD 990 PRO", "SSD 870 EVO"]),
    ], [""]),
    "Periféricos": ((19, 199), (0.30, 0.45), [
        ("Logitech", ["MX Master 3S", "G502 HERO", "MX Keys S", "G PRO X Superlight", "C920 Webcam"]),
        ("Microsoft", ["Ergonomic Mouse", "Surface Keyboard"]),
        ("ASUS", ["ROG Gladius III", "TUF Gaming K3"]),
        ("HP", ["Teclado 230 inalámbrico"]),
    ], ["Negro", "Blanco"]),
    "Smartphones": ((149, 1599), (0.08, 0.18), [
        ("Apple", ["iPhone 15", "iPhone 16", "iPhone 16 Pro"]),
        ("Samsung", ["Galaxy S24", "Galaxy A55", "Galaxy Z Flip6"]),
        ("Xiaomi", ["Redmi Note 13", "Xiaomi 14T"]),
        ("Sony", ["Xperia 10 VI"]),
    ], ["128GB", "256GB", "512GB"]),
    "Smartwatches": ((49, 899), (0.15, 0.28), [
        ("Apple", ["Watch Series 10", "Watch SE"]),
        ("Samsung", ["Galaxy Watch7"]),
        ("Xiaomi", ["Smart Band 9", "Watch S3"]),
        ("Garmin", ["Forerunner 265", "Venu 3", "Fenix 8"]),
    ], ["41mm", "45mm"]),
    "Accesorios móvil": ((9, 79), (0.40, 0.60), [
        ("Apple", ["Funda MagSafe", "Cargador USB-C 20W"]),
        ("Samsung", ["Cargador 25W", "Funda Silicone"]),
        ("Xiaomi", ["Power Bank 10000mAh", "Cable USB-C 1m"]),
    ], ["Negro", "Azul", "Transparente"]),
    "Televisores": ((299, 3499), (0.10, 0.20), [
        ("Samsung", ["Crystal UHD", "Neo QLED", "OLED S90D"]),
        ("LG", ["OLED evo C4", "QNED 82", "NanoCell 81"]),
        ("Sony", ["Bravia 7", "Bravia 9"]),
        ("Xiaomi", ["TV A Pro"]),
    ], ['43"', '55"', '65"', '75"']),
    "Barras de sonido": ((99, 999), (0.15, 0.28), [
        ("Samsung", ["HW-Q600C", "HW-Q990D"]),
        ("LG", ["S70TY"]),
        ("Sony", ["HT-S2000", "Bravia Theatre Bar 8"]),
        ("Bose", ["Smart Soundbar", "Smart Ultra Soundbar"]),
        ("JBL", ["Bar 500", "Bar 1000"]),
    ], [""]),
    "Auriculares": ((19, 549), (0.20, 0.35), [
        ("Apple", ["AirPods 4", "AirPods Pro 2", "AirPods Max"]),
        ("Sony", ["WH-1000XM5", "WF-1000XM5"]),
        ("Bose", ["QuietComfort Ultra", "QuietComfort Earbuds"]),
        ("JBL", ["Tune 520BT", "Live 770NC"]),
        ("Samsung", ["Galaxy Buds3 Pro"]),
        ("Xiaomi", ["Redmi Buds 6"]),
    ], ["Negro", "Blanco"]),
    "Consolas": ((199, 799), (0.05, 0.12), [
        ("Sony", ["PlayStation 5 Slim", "PlayStation 5 Pro"]),
        ("Microsoft", ["Xbox Series S", "Xbox Series X"]),
        ("Nintendo", ["Switch Lite", "Switch OLED"]),
    ], ["Estándar", "Pack con juego"]),
    "Videojuegos": ((19, 79), (0.20, 0.35), [
        ("Nintendo", ["Mario Kart 8 Deluxe", "Zelda: Tears of the Kingdom", "Animal Crossing"]),
        ("Sony", ["Gran Turismo 7", "Marvel's Spider-Man 2", "God of War Ragnarök"]),
        ("Microsoft", ["Forza Horizon 5", "Halo Infinite", "Starfield"]),
    ], ["Edición estándar", "Edición deluxe"]),
    "Sillas gaming": ((149, 499), (0.25, 0.40), [
        ("MSI", ["MAG CH130"]),
        ("ASUS", ["ROG Chariot"]),
        ("Cecotec", ["DarkWarrior"]),
    ], ["Negro", "Rojo", "Azul"]),
    "Robots aspiradores": ((149, 1299), (0.18, 0.30), [
        ("Roborock", ["S8", "Q Revo", "Qrevo Curv"]),
        ("Xiaomi", ["Robot Vacuum X20"]),
        ("Cecotec", ["Conga 2290", "Conga 8290"]),
        ("Dyson", ["360 Vis Nav"]),
    ], [""]),
    "Pequeño electrodoméstico": ((29, 699), (0.25, 0.40), [
        ("Dyson", ["V15 Detect", "Supersonic", "Airwrap"]),
        ("Cecotec", ["Cecofry Freidora de aire", "Power Espresso 20", "Mambo Robot de cocina"]),
        ("Xiaomi", ["Smart Air Fryer"]),
    ], [""]),
    "Domótica": ((15, 249), (0.30, 0.45), [
        ("Xiaomi", ["Smart Plug", "Cámara C300", "Bombilla inteligente"]),
        ("Apple", ["HomePod mini", "AirTag"]),
        ("Samsung", ["SmartThings Hub"]),
    ], ["Unidad", "Pack 4"]),
}

# Peso de cada ciudad al repartir clientes (las grandes tienen más).
# Las que no aparecen tienen peso 2.
PESO_CIUDAD = {
    "Madrid": 30, "Barcelona": 18, "Valencia": 8, "Sevilla": 7, "Málaga": 5,
    "Bilbao": 5, "Zaragoza": 5, "Las Rozas de Madrid": 4, "Getafe": 3,
}

# Los 2 primeros dígitos del código postal español = provincia
CP_PROVINCIA = {
    "Madrid": "28", "Barcelona": "08", "Valencia": "46", "Sevilla": "41", "Málaga": "29",
    "Bizkaia": "48", "Zaragoza": "50", "Valladolid": "47", "A Coruña": "15",
    "Alicante": "03", "Murcia": "30", "Illes Balears": "07", "Granada": "18",
    "Salamanca": "37", "Asturias": "33",
}

DOMINIOS_EMAIL = ["gmail.com", "hotmail.com", "outlook.es", "yahoo.es", "icloud.com"]


# ---------------------------------------------------------------------
# 2. FUNCIONES AUXILIARES
# ---------------------------------------------------------------------

def fecha_aleatoria(desde: date, hasta: date) -> date:
    return desde + timedelta(days=random.randint(0, (hasta - desde).days))


def precio_comercial(valor: float) -> float:
    """1234.56 -> 1229.99 / 45.3 -> 44.99 (precios acabados en ,99)."""
    if valor >= 100:
        return round(valor, -1) - 0.01
    return max(round(valor), 1) - 0.01


def sin_acentos(texto: str) -> str:
    """'José Núñez' -> 'jose.nunez' (para construir emails)."""
    normal = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return normal.lower().replace(" ", ".")


def telefono_movil() -> str:
    return f"6{random.randint(10, 99)} {random.randint(100, 999)} {random.randint(100, 999)}"


# ---------------------------------------------------------------------
# 3. GENERADORES
# ---------------------------------------------------------------------

def insertar_productos(cur):
    cur.execute("SELECT nombre, id_categoria FROM categoria WHERE id_categoria_padre IS NOT NULL")
    ids_categoria = dict(cur.fetchall())
    cur.execute("SELECT nombre, id_marca FROM marca")
    ids_marca = dict(cur.fetchall())

    productos = []
    for subcat, ((p_min, p_max), (m_min, m_max), lineas, variantes) in CATALOGO.items():
        for marca, modelos in lineas:
            for modelo in modelos:
                # Precio base del modelo; cada variante "superior" es un 15 % más cara
                base = random.uniform(p_min, p_max * 0.7)
                for i, variante in enumerate(variantes):
                    precio = precio_comercial(min(base * (1 + 0.15 * i), p_max))
                    margen = random.uniform(m_min, m_max)
                    coste = round(precio * (1 - margen), 2)

                    nombre = f"{marca} {modelo} {variante}".strip()
                    sku = f"{subcat[:3].upper()}-{marca[:3].upper()}-{len(productos) + 1:05d}"
                    fecha_alta = fecha_aleatoria(date(2022, 6, 1), date(2025, 9, 30))
                    activo = random.random() < 0.92  # un 8 % ya descatalogados

                    productos.append((
                        sku, nombre, ids_categoria[subcat], ids_marca[marca],
                        precio, coste, 36, activo, fecha_alta,
                    ))

    cur.executemany(
        """INSERT INTO producto (sku, nombre, id_categoria, id_marca, precio_venta,
                                 coste, meses_garantia, activo, fecha_alta)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        productos,
    )


def insertar_clientes(cur):
    cur.execute("SELECT id_nivel FROM nivel_fidelidad WHERE nombre = 'Bronce'")
    id_bronce = cur.fetchone()[0]

    dias_periodo = (FECHA_FIN - date(2022, 1, 1)).days
    emails_usados = set()
    clientes = []

    for _ in range(NUM_CLIENTES):
        nombre = fake.first_name()
        apellidos = f"{fake.last_name()} {fake.last_name()}"

        # Email único: nombre.apellido + número si ya existe
        base = f"{sin_acentos(nombre)}.{sin_acentos(apellidos.split()[0])}"
        email, n = f"{base}@{random.choice(DOMINIOS_EMAIL)}", 1
        while email in emails_usados:
            n += 1
            email = f"{base}{n}@{random.choice(DOMINIOS_EMAIL)}"
        emails_usados.add(email)

        # Distribución triangular: más registros en los años recientes (la tienda crece)
        dias = int(random.triangular(0, dias_periodo, dias_periodo))
        fecha_registro = date(2022, 1, 1) + timedelta(days=dias)

        clientes.append((
            nombre, apellidos, email,
            telefono_movil() if random.random() < 0.9 else None,  # 10 % sin teléfono
            fake.date_of_birth(minimum_age=18, maximum_age=75),
            fecha_registro, 0, id_bronce,
        ))

    cur.executemany(
        """INSERT INTO cliente (nombre, apellidos, email, telefono, fecha_nacimiento,
                                fecha_registro, puntos, id_nivel)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        clientes,
    )


def insertar_direcciones(cur):
    cur.execute("SELECT id_ciudad, nombre, provincia FROM ciudad")
    ciudades = cur.fetchall()
    pesos = [PESO_CIUDAD.get(nombre, 2) for _, nombre, _ in ciudades]

    cur.execute("SELECT id_cliente FROM cliente")
    ids_cliente = [fila[0] for fila in cur.fetchall()]

    direcciones = []
    for id_cliente in ids_cliente:
        num_direcciones = 2 if random.random() < 0.25 else 1  # 25 % tiene 2 (casa + trabajo)
        for i in range(num_direcciones):
            id_ciudad, _, provincia = random.choices(ciudades, weights=pesos)[0]
            cp = CP_PROVINCIA[provincia] + f"{random.randint(0, 999):03d}"
            direcciones.append((id_cliente, fake.street_address(), cp, id_ciudad, i == 0))

    cur.executemany(
        """INSERT INTO direccion (id_cliente, calle, codigo_postal, id_ciudad, es_principal)
           VALUES (%s, %s, %s, %s, %s)""",
        direcciones,
    )


def insertar_empleado(cur, puesto, id_ubicacion, id_jefe, fecha):
    cur.execute(
        """INSERT INTO empleado (nombre, apellidos, puesto, id_ubicacion, id_jefe, fecha_contratacion)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING id_empleado""",
        (fake.first_name(), f"{fake.last_name()} {fake.last_name()}", puesto,
         id_ubicacion, id_jefe, fecha),
    )
    return cur.fetchone()[0]


def insertar_empleados(cur):
    """
    Jerarquía (auto-relación id_jefe):
        Director general
          ├── Encargado de tienda ── Vendedores / Técnico
          └── Jefe de almacén ────── Operarios de almacén
    """
    cur.execute("SELECT id_ubicacion, nombre, tipo, fecha_apertura FROM ubicacion ORDER BY id_ubicacion")
    ubicaciones = cur.fetchall()

    sede = next(u for u in ubicaciones if u[1] == "TechNova Madrid Gran Vía")
    id_director = insertar_empleado(cur, "Director general", sede[0], None, sede[3])

    for id_ubi, _, tipo, apertura in ubicaciones:
        if tipo == "tienda":
            jefe = insertar_empleado(cur, "Encargado de tienda", id_ubi, id_director, apertura)
            plantilla = [("Vendedor", random.randint(4, 9)), ("Técnico", random.randint(1, 2))]
        else:
            jefe = insertar_empleado(cur, "Jefe de almacén", id_ubi, id_director, apertura)
            plantilla = [("Operario de almacén", random.randint(6, 12))]

        for puesto, cantidad in plantilla:
            for _ in range(cantidad):
                insertar_empleado(cur, puesto, id_ubi, jefe, fecha_aleatoria(apertura, FECHA_FIN))


def mostrar_resumen(cur):
    print("\n📊 Filas cargadas:")
    for tabla in ["producto", "cliente", "direccion", "empleado"]:
        cur.execute(f"SELECT COUNT(*) FROM {tabla}")
        print(f"   {tabla:<10} {cur.fetchone()[0]:>6}")


# ---------------------------------------------------------------------
# 4. PROGRAMA PRINCIPAL
# ---------------------------------------------------------------------

def main():
    random.seed(SEMILLA)
    Faker.seed(SEMILLA)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE producto, cliente, empleado RESTART IDENTITY CASCADE")
        insertar_productos(cur)
        insertar_clientes(cur)
        insertar_direcciones(cur)
        insertar_empleados(cur)
        mostrar_resumen(cur)

    print("\n✅ Productos, clientes y empleados generados")


if __name__ == "__main__":
    main()