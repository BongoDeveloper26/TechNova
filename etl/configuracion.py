"""
configuracion.py -> Parámetros del ETL.

Aquí está TODO lo que puede cambiar sin tocar la lógica:
  - Rutas de ficheros
  - Estrategia de carga de cada tabla de la OLTP
  - El "contrato de datos" de cada proveedor (cómo es su CSV)
  - Umbrales de calidad
"""
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CARPETA_LANDING = RAIZ / "data" / "landing" / "proveedores"   # aquí "llegan" los CSV
CARPETA_LOGS = RAIZ / "logs"
FICHERO_ESQUEMA_DW = RAIZ / "sql" / "dw" / "01_dw_schema.sql"

# ---------------------------------------------------------------------
# 1. EXTRACCIÓN DE LA OLTP -> staging.oltp_<tabla>
#
#   "completa":    se vacía y se copia entera. Para tablas pequeñas o que cambian mucho.
#   "incremental": solo filas con id mayor que el último cargado. Para tablas
#                  donde solo se AÑADEN filas (nunca se modifican).
#   "ventana":     filas de los últimos N días respecto a la última carga, con UPSERT.
#                  Para tablas grandes cuyas filas recientes pueden cambiar
#                  (un pedido pasa de 'pagado' a 'enviado' a 'entregado'...).
# ---------------------------------------------------------------------
ESTRATEGIAS_OLTP = {
    # Maestros y tablas pequeñas
    "nivel_fidelidad":    {"tipo": "completa"},
    "ciudad":             {"tipo": "completa"},
    "categoria":          {"tipo": "completa"},
    "marca":              {"tipo": "completa"},
    "producto":           {"tipo": "completa"},
    "ubicacion":          {"tipo": "completa"},
    "empleado":           {"tipo": "completa"},
    "proveedor":          {"tipo": "completa"},
    "promocion":          {"tipo": "completa"},
    "promocion_producto": {"tipo": "completa"},
    "cupon":              {"tipo": "completa"},
    "cliente":            {"tipo": "completa"},   # cambian sus puntos y nivel
    "direccion":          {"tipo": "completa"},
    "stock":              {"tipo": "completa"},   # es una "foto" del momento
    "envio":              {"tipo": "completa"},
    "pedido_compra":      {"tipo": "completa"},
    "linea_compra":       {"tipo": "completa"},
    # Tablas grandes
    "linea_pedido":       {"tipo": "incremental", "columna": "id_linea"},
    "pago":               {"tipo": "incremental", "columna": "id_pago"},
    "pedido":             {"tipo": "ventana", "columna": "fecha", "dias": 30},
    "devolucion":         {"tipo": "ventana", "columna": "fecha", "dias": 60},
    "garantia":           {"tipo": "ventana", "columna": "fecha_reclamacion", "dias": 120},
}

# ---------------------------------------------------------------------
# 2. API DE TIPOS DE CAMBIO (Frankfurter v2, datos oficiales del BCE)
# ---------------------------------------------------------------------
API_DIVISAS_URL = "https://api.frankfurter.dev/v2/rates"
API_DIVISAS_PROVEEDOR = "ECB"              # Banco Central Europeo
MONEDAS = ["USD", "JPY", "GBP"]
DIVISAS_DESDE = date(2022, 12, 1)          # primera carga: cubre todas las compras
API_TIMEOUT_SEG = 30
API_REINTENTOS = 3

# ---------------------------------------------------------------------
# 3. CONTRATO DE DATOS DE CADA PROVEEDOR
#    Cada proveedor manda su CSV como le da la gana (como en la vida real):
#    separador, decimales, formato de fecha, codificación y nombres de columna.
#    El contrato traduce SU formato a NUESTRO formato.
# ---------------------------------------------------------------------
COLUMNAS_CANONICAS = ["sku", "descripcion", "precio_coste", "moneda",
                      "stock_disponible", "plazo_entrega_dias", "fecha_tarifa"]

CONTRATOS_PROVEEDOR = {
    "iberia_tech": {
        "nombre": "Iberia Tech Distribución S.L.",
        "moneda": "EUR", "separador": ";", "decimal": ",", "miles": ".",
        "formato_fecha": "%d/%m/%Y", "encoding": "latin-1",
        "columnas": {"CODIGO": "sku", "DESCRIPCION": "descripcion", "PRECIO": "precio_coste",
                     "MONEDA": "moneda", "STOCK": "stock_disponible", "PLAZO": "plazo_entrega_dias",
                     "FECHA": "fecha_tarifa"},
    },
    "eurogadget": {
        "nombre": "EuroGadget Wholesale GmbH",
        "moneda": "EUR", "separador": ";", "decimal": ",", "miles": ".",
        "formato_fecha": "%d.%m.%Y", "encoding": "utf-8",
        "columnas": {"Artikelnummer": "sku", "Bezeichnung": "descripcion", "Preis": "precio_coste",
                     "Waehrung": "moneda", "Bestand": "stock_disponible", "Lieferzeit": "plazo_entrega_dias",
                     "Datum": "fecha_tarifa"},
    },
    "pacific_electronics": {
        "nombre": "Pacific Electronics Supply Ltd.",
        "moneda": "USD", "separador": ",", "decimal": ".", "miles": "",
        "formato_fecha": "%Y/%m/%d", "encoding": "utf-8",
        "columnas": {"sku": "sku", "description": "descripcion", "unit_price": "precio_coste",
                     "currency": "moneda", "qty_available": "stock_disponible",
                     "lead_time_days": "plazo_entrega_dias", "price_date": "fecha_tarifa"},
    },
    "atlantic_devices": {
        "nombre": "Atlantic Devices Inc.",
        "moneda": "USD", "separador": ",", "decimal": ".", "miles": ",",
        "formato_fecha": "%m/%d/%Y", "encoding": "utf-8",
        "columnas": {"SKU": "sku", "Item Name": "descripcion", "Unit Cost": "precio_coste",
                     "Currency": "moneda", "On Hand": "stock_disponible", "Lead Time": "plazo_entrega_dias",
                     "Date": "fecha_tarifa"},
    },
    "nippon_digital": {
        "nombre": "Nippon Digital Trading K.K.",
        "moneda": "JPY", "separador": ",", "decimal": ".", "miles": "",
        "formato_fecha": "%Y-%m-%d", "encoding": "utf-8",
        "columnas": {"item_code": "sku", "item_name": "descripcion", "price": "precio_coste",
                     "currency": "moneda", "stock": "stock_disponible", "lead_days": "plazo_entrega_dias",
                     "date": "fecha_tarifa"},
    },
    "albion_tech": {
        "nombre": "Albion Tech Distribution Ltd.",
        "moneda": "GBP", "separador": ",", "decimal": ".", "miles": ",",
        "formato_fecha": "%d/%m/%Y", "encoding": "utf-8",
        "columnas": {"Product Code": "sku", "Product": "descripcion", "Cost": "precio_coste",
                     "Currency": "moneda", "Stock": "stock_disponible", "Lead Time (days)": "plazo_entrega_dias",
                     "Date": "fecha_tarifa"},
    },
}

# ---------------------------------------------------------------------
# 4. UMBRALES DE CALIDAD
# ---------------------------------------------------------------------
# Si un fichero tiene más de este % de filas malas, se descarta ENTERO
# (seguramente el proveedor ha mandado un fichero roto: mejor no cargar nada)
UMBRAL_RECHAZO_FICHERO = 0.25

# Un precio de proveedor (en €) fuera de este rango respecto al coste que
# conocemos se considera anómalo (p. ej. alguien escribió 129900 en vez de 1299,00)
RANGO_PRECIO_VALIDO = (0.5, 2.0)