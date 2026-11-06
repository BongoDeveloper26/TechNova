"""
seed_maestros.py -> Fase 2.2: datos maestros de TechNova.

Los "datos maestros" son los que casi no cambian y de los que dependen
todos los demás: niveles de fidelidad, ciudades, categorías, marcas,
tiendas/almacenes y proveedores.

Se puede ejecutar varias veces: primero vacía las tablas y luego las rellena.
"""
from db import get_connection

# ---------------------------------------------------------------------
# 1. DATOS
# ---------------------------------------------------------------------

# (nombre, puntos_minimos, descuento_pct)
NIVELES = [
    ("Bronce", 0, 0),
    ("Plata", 1000, 3),
    ("Oro", 5000, 5),
    ("Platino", 15000, 8),
]

# (nombre, provincia)
CIUDADES = [
    ("Madrid", "Madrid"),
    ("Las Rozas de Madrid", "Madrid"),
    ("Getafe", "Madrid"),
    ("Barcelona", "Barcelona"),
    ("El Prat de Llobregat", "Barcelona"),
    ("Valencia", "Valencia"),
    ("Sevilla", "Sevilla"),
    ("Málaga", "Málaga"),
    ("Bilbao", "Bizkaia"),
    ("Zaragoza", "Zaragoza"),
    ("Valladolid", "Valladolid"),
    ("A Coruña", "A Coruña"),
    ("Alicante", "Alicante"),
    ("Murcia", "Murcia"),
    ("Palma", "Illes Balears"),
    ("Granada", "Granada"),
    ("Salamanca", "Salamanca"),
    ("Oviedo", "Asturias"),
]

# Categoría padre -> lista de subcategorías (auto-relación)
CATEGORIAS = {
    "Informática": ["Portátiles", "Ordenadores de sobremesa", "Monitores", "Componentes", "Periféricos"],
    "Telefonía": ["Smartphones", "Smartwatches", "Accesorios móvil"],
    "Imagen y sonido": ["Televisores", "Barras de sonido", "Auriculares"],
    "Gaming": ["Consolas", "Videojuegos", "Sillas gaming"],
    "Hogar inteligente": ["Robots aspiradores", "Pequeño electrodoméstico", "Domótica"],
}

# (nombre, pais_origen)
MARCAS = [
    ("Apple", "Estados Unidos"), ("Samsung", "Corea del Sur"), ("Xiaomi", "China"),
    ("Lenovo", "China"), ("HP", "Estados Unidos"), ("ASUS", "Taiwán"),
    ("MSI", "Taiwán"), ("Dell", "Estados Unidos"), ("Acer", "Taiwán"),
    ("LG", "Corea del Sur"), ("Sony", "Japón"), ("Logitech", "Suiza"),
    ("Nintendo", "Japón"), ("Microsoft", "Estados Unidos"), ("Bose", "Estados Unidos"),
    ("JBL", "Estados Unidos"), ("Dyson", "Reino Unido"), ("Roborock", "China"),
    ("Cecotec", "España"), ("Garmin", "Estados Unidos"),
]

# (nombre, tipo, ciudad, direccion, fecha_apertura)
UBICACIONES = [
    ("Almacén Central Getafe", "almacen", "Getafe", "Polígono Los Olivos, nave 12", "2015-03-01"),
    ("Almacén Noreste El Prat", "almacen", "El Prat de Llobregat", "Zona Logística ZAL, nave 4", "2017-06-15"),
    ("Almacén Sur Sevilla", "almacen", "Sevilla", "Polígono La Isla, parcela 8", "2019-09-01"),
    ("TechNova Madrid Gran Vía", "tienda", "Madrid", "Gran Vía 45", "2015-10-20"),
    ("TechNova Las Rozas", "tienda", "Las Rozas de Madrid", "C.C. Heron City, local 21", "2018-04-12"),
    ("TechNova Barcelona Diagonal", "tienda", "Barcelona", "Avinguda Diagonal 210", "2016-05-05"),
    ("TechNova Valencia", "tienda", "Valencia", "Calle Colón 30", "2017-11-18"),
    ("TechNova Sevilla", "tienda", "Sevilla", "Calle Sierpes 52", "2019-11-22"),
    ("TechNova Málaga", "tienda", "Málaga", "Calle Larios 10", "2020-03-02"),
    ("TechNova Bilbao", "tienda", "Bilbao", "Gran Vía de Don Diego López de Haro 25", "2018-09-14"),
    ("TechNova Zaragoza", "tienda", "Zaragoza", "Paseo de la Independencia 18", "2021-06-01"),
    ("TechNova Valladolid", "tienda", "Valladolid", "Calle Santiago 15", "2022-10-07"),
]

# Proveedores ficticios. Algunos cobran en otra moneda -> en la Fase 4
# usaremos una API de tipos de cambio para pasar todo a euros.
# (nombre, cif, pais, moneda, email)
PROVEEDORES = [
    ("Iberia Tech Distribución S.L.", "B12345678", "España", "EUR", "pedidos@iberiatech.example"),
    ("EuroGadget Wholesale GmbH", "DE811223344", "Alemania", "EUR", "orders@eurogadget.example"),
    ("Pacific Electronics Supply Ltd.", "CN-91440300", "China", "USD", "sales@pacificelec.example"),
    ("Atlantic Devices Inc.", "US-47-1234567", "Estados Unidos", "USD", "b2b@atlanticdevices.example"),
    ("Nippon Digital Trading K.K.", "JP-0104012345", "Japón", "JPY", "export@nippondigital.example"),
    ("Albion Tech Distribution Ltd.", "GB-123456789", "Reino Unido", "GBP", "trade@albiontech.example"),
]

# Orden de borrado: CASCADE vacía también las tablas que dependen de estas
TABLAS_MAESTRAS = ["nivel_fidelidad", "ciudad", "categoria", "marca", "ubicacion", "proveedor"]


# ---------------------------------------------------------------------
# 2. FUNCIONES DE CARGA
# ---------------------------------------------------------------------

def vaciar_tablas(cur):
    # RESTART IDENTITY -> los ids vuelven a empezar en 1
    # CASCADE          -> también vacía las tablas que dependen de estas
    cur.execute(f"TRUNCATE {', '.join(TABLAS_MAESTRAS)} RESTART IDENTITY CASCADE")


def insertar_niveles(cur):
    cur.executemany(
        "INSERT INTO nivel_fidelidad (nombre, puntos_minimos, descuento_pct) VALUES (%s, %s, %s)",
        NIVELES,
    )


def insertar_ciudades(cur):
    cur.executemany("INSERT INTO ciudad (nombre, provincia) VALUES (%s, %s)", CIUDADES)


def insertar_categorias(cur):
    for padre, hijas in CATEGORIAS.items():
        # 1) insertamos la categoría padre y recuperamos su id con RETURNING
        cur.execute(
            "INSERT INTO categoria (nombre) VALUES (%s) RETURNING id_categoria",
            (padre,),
        )
        id_padre = cur.fetchone()[0]

        # 2) las subcategorías apuntan al padre (auto-relación)
        cur.executemany(
            "INSERT INTO categoria (nombre, id_categoria_padre) VALUES (%s, %s)",
            [(hija, id_padre) for hija in hijas],
        )


def insertar_marcas(cur):
    cur.executemany("INSERT INTO marca (nombre, pais_origen) VALUES (%s, %s)", MARCAS)


def insertar_ubicaciones(cur):
    # Diccionario {nombre_ciudad: id_ciudad} para traducir nombres a FKs
    cur.execute("SELECT nombre, id_ciudad FROM ciudad")
    ids_ciudad = dict(cur.fetchall())

    cur.executemany(
        """INSERT INTO ubicacion (nombre, tipo, id_ciudad, direccion, fecha_apertura)
           VALUES (%s, %s, %s, %s, %s)""",
        [(nombre, tipo, ids_ciudad[ciudad], direccion, fecha)
         for nombre, tipo, ciudad, direccion, fecha in UBICACIONES],
    )


def insertar_proveedores(cur):
    cur.executemany(
        "INSERT INTO proveedor (nombre, cif, pais, moneda, email) VALUES (%s, %s, %s, %s, %s)",
        PROVEEDORES,
    )


def mostrar_resumen(cur):
    print("\n📊 Filas cargadas:")
    for tabla in TABLAS_MAESTRAS:
        cur.execute(f"SELECT COUNT(*) FROM {tabla}")
        print(f"   {tabla:<16} {cur.fetchone()[0]:>4}")


# ---------------------------------------------------------------------
# 3. PROGRAMA PRINCIPAL
# ---------------------------------------------------------------------

def main():
    # "with" = TRANSACCIÓN: si algo falla a mitad, no se guarda nada (rollback).
    # Si todo va bien, al salir del bloque se hace commit automáticamente.
    with get_connection() as conn, conn.cursor() as cur:
        vaciar_tablas(cur)
        insertar_niveles(cur)
        insertar_ciudades(cur)
        insertar_categorias(cur)
        insertar_marcas(cur)
        insertar_ubicaciones(cur)
        insertar_proveedores(cur)
        mostrar_resumen(cur)

    print("\n✅ Datos maestros cargados correctamente")


if __name__ == "__main__":
    main()