"""
simular_proveedores.py -> Simula los ficheros CSV que mandan los proveedores cada día.

Esto NO es parte del ETL: hace de "mundo exterior". En una empresa real
estos ficheros llegarían por SFTP, email o un bucket de S3.

Cada proveedor usa SU formato (ver CONTRATOS_PROVEEDOR en configuracion.py)
y, además, se cuelan errores típicos para que el ETL tenga trabajo:
  - SKU en minúsculas o con espacios        (se puede arreglar)
  - Precio vacío, con texto o negativo      (se rechaza)
  - Stock vacío                             (se rechaza)
  - SKU que no existe en nuestro catálogo   (se rechaza)
  - Filas duplicadas                        (se queda la última)
  - Precio con error de tecleo (x100)       (se rechaza por anómalo)
  - Fecha imposible                         (se rechaza)
  - De vez en cuando, un fichero entero roto (se descarta completo)
Los domingos no se envían ficheros.

Uso:
    python etl/simular_proveedores.py --desde 2025-12-01 --hasta 2025-12-31
"""
import argparse
import csv
import random
import sys
from datetime import date, timedelta

from configuracion import CARPETA_LANDING, CONTRATOS_PROVEEDOR, RAIZ
from conexiones import conectar_oltp

sys.path.insert(0, str(RAIZ / "data_generator"))
from seed_inventario import PROVEEDOR_POR_MARCA  # noqa: E402  (qué proveedor sirve cada marca)

# Tipo de cambio aproximado que "usa" cada proveedor para fijar su precio
TASA_APROX = {"EUR": 1.0, "USD": 1.16, "JPY": 175.0, "GBP": 0.87}

PLAZO_BASE = {"EUR": (2, 5), "GBP": (4, 8), "USD": (12, 25), "JPY": (15, 30)}

PROB_FICHERO_ROTO = 0.02
ERRORES = [  # (tipo de error, probabilidad por fila)
    ("sku_formato", 0.03), ("precio_vacio", 0.01), ("precio_negativo", 0.005),
    ("stock_vacio", 0.01), ("sku_inexistente", 0.005), ("duplicado", 0.01),
    ("precio_x100", 0.005), ("fecha_imposible", 0.003),
]


def formatear_numero(valor, contrato, decimales=2):
    """1234.5 -> '1.234,50' (europeo) / '1,234.50' (inglés) / '1234.50' (sin miles)."""
    texto = f"{valor:,.{decimales}f}"                      # '1,234.50'
    texto = texto.replace(",", "@").replace(".", contrato["decimal"])
    return texto.replace("@", contrato["miles"])


def cargar_catalogo():
    with conectar_oltp() as conn:
        filas = conn.execute("""
            SELECT p.sku, p.nombre, p.coste, m.nombre
            FROM oltp.producto p JOIN oltp.marca m USING (id_marca)
            WHERE p.activo
            ORDER BY p.sku
        """).fetchall()
    por_proveedor = {}
    for sku, nombre, coste, marca in filas:
        por_proveedor.setdefault(PROVEEDOR_POR_MARCA[marca], []).append((sku, nombre, float(coste)))
    return por_proveedor


def generar_filas(rng, productos, contrato, dia):
    moneda = contrato["moneda"]
    decimales = 0 if moneda == "JPY" else 2
    roto = rng.random() < PROB_FICHERO_ROTO
    filas = []

    for sku, nombre, coste in productos:
        if rng.random() < 0.08:
            continue  # ese día el proveedor no incluye el producto
        # Precio estable por producto (semilla = sku) con una pequeña variación diaria
        ajuste_producto = random.Random(sku).uniform(-0.08, 0.08)
        precio = coste * TASA_APROX[moneda] * (1 + ajuste_producto) * rng.uniform(0.99, 1.01)
        fila = {
            "sku": sku, "descripcion": nombre,
            "precio_coste": formatear_numero(precio, contrato, decimales),
            "moneda": moneda,
            "stock_disponible": str(rng.choice([0, 0, rng.randint(1, 30), rng.randint(30, 500)])),
            "plazo_entrega_dias": str(rng.randint(*PLAZO_BASE[moneda])),
            "fecha_tarifa": dia.strftime(contrato["formato_fecha"]),
        }

        if roto:
            fila["precio_coste"] = "#N/A"
        else:
            for error, prob in ERRORES:
                if rng.random() >= prob:
                    continue
                if error == "sku_formato":
                    fila["sku"] = f" {sku.lower()} "
                elif error == "precio_vacio":
                    fila["precio_coste"] = rng.choice(["", "N/D", "consultar"])
                elif error == "precio_negativo":
                    fila["precio_coste"] = "-" + fila["precio_coste"]
                elif error == "stock_vacio":
                    fila["stock_disponible"] = ""
                elif error == "sku_inexistente":
                    fila["sku"] = f"XXX-{rng.randint(10000, 99999)}"
                elif error == "precio_x100":
                    fila["precio_coste"] = formatear_numero(precio * 100, contrato, decimales)
                elif error == "fecha_imposible":
                    fila["fecha_tarifa"] = "31/02/2025"
                elif error == "duplicado":
                    filas.append(dict(fila))  # la misma fila dos veces
        filas.append(fila)
    return filas


def escribir_csv(ruta, filas, contrato):
    inverso = {canonica: suya for suya, canonica in contrato["columnas"].items()}
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", newline="", encoding=contrato["encoding"], errors="replace") as f:
        escritor = csv.writer(f, delimiter=contrato["separador"])
        escritor.writerow(inverso[c] for c in inverso)
        for fila in filas:
            escritor.writerow(fila[c] for c in inverso)


def main():
    parser = argparse.ArgumentParser(description="Simula los CSV diarios de los proveedores")
    parser.add_argument("--desde", type=date.fromisoformat, default=date.today())
    parser.add_argument("--hasta", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()

    catalogo = cargar_catalogo()
    total = 0
    dia = args.desde
    while dia <= args.hasta:
        if dia.weekday() != 6:  # los domingos no se envía nada
            for codigo, contrato in CONTRATOS_PROVEEDOR.items():
                rng = random.Random(f"{dia}-{codigo}")  # reproducible: mismo día -> mismo fichero
                filas = generar_filas(rng, catalogo.get(contrato["nombre"], []), contrato, dia)
                escribir_csv(CARPETA_LANDING / dia.isoformat() / f"{codigo}.csv", filas, contrato)
                total += 1
        dia += timedelta(days=1)
    print(f"{total} ficheros generados en {CARPETA_LANDING.relative_to(RAIZ).as_posix()}/")


if __name__ == "__main__":
    main()