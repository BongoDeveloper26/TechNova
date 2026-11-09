"""
proveedores.py -> ETL de los CSV diarios de tarifas de proveedores.

Es la parte más "sucia" del proyecto, como en la vida real:
cada proveedor manda su fichero en un formato distinto y con errores.

  E: busca en data/landing/proveedores/<fecha>/<proveedor>.csv los ficheros
     que aún no se han procesado (se controla con su hash SHA-256).
  T: 1) Lee TODO como texto (nunca dejes que pandas adivine los tipos)
     2) Traduce las columnas del proveedor a las nuestras (contrato de datos)
     3) Limpia: SKU en mayúsculas sin espacios, números con coma decimal, fechas...
     4) Valida cada fila y apunta el motivo de las que no pasan
     5) Convierte el precio a euros con el tipo de cambio de ese día
  L: UPSERT de las filas válidas en staging.proveedor_tarifa
     y las rechazadas en etl.rechazo (con la fila original, para poder revisarla).
"""
import hashlib
import json
from pathlib import Path

import pandas as pd

from configuracion import (CARPETA_LANDING, COLUMNAS_CANONICAS, CONTRATOS_PROVEEDOR, RAIZ,
                           RANGO_PRECIO_VALIDO, UMBRAL_RECHAZO_FICHERO)
from registro import log


# ---------------------------------------------------------------------
# EXTRACT
# ---------------------------------------------------------------------

def hash_fichero(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def ficheros_pendientes(conn_dw, fecha_proceso):
    """Ficheros con fecha <= fecha_proceso que todavía no se han procesado."""
    procesados = set(conn_dw.execute(
        "SELECT nombre_fichero, hash_sha256 FROM etl.fichero_procesado").fetchall())
    pendientes = []
    for ruta in sorted(CARPETA_LANDING.glob("*/*.csv")):
        try:
            fecha_carpeta = pd.Timestamp(ruta.parent.name).date()
        except ValueError:
            log.warning(f"   Carpeta con nombre no válido, se ignora: {ruta.parent.name}")
            continue
        if fecha_carpeta > fecha_proceso:
            continue
        nombre = ruta.relative_to(RAIZ).as_posix()
        if (nombre, hash_fichero(ruta)) not in procesados:
            pendientes.append(ruta)
    return pendientes


def leer_csv(ruta: Path, contrato: dict) -> pd.DataFrame:
    df = pd.read_csv(ruta, sep=contrato["separador"], encoding=contrato["encoding"],
                     dtype=str, keep_default_na=False)
    faltan = set(contrato["columnas"]) - set(df.columns)
    if faltan:
        raise ValueError(f"El fichero no cumple el contrato, faltan columnas: {sorted(faltan)}")
    df = df.rename(columns=contrato["columnas"])[COLUMNAS_CANONICAS]
    df.insert(0, "num_fila", range(2, len(df) + 2))  # nº de fila real en el CSV (la 1 es la cabecera)
    return df


# ---------------------------------------------------------------------
# TRANSFORM
# ---------------------------------------------------------------------

def a_numero(serie: pd.Series, contrato: dict) -> pd.Series:
    """'1.234,56' (formato europeo) o '1,234.56' (formato inglés) -> 1234.56"""
    texto = serie.str.strip()
    if contrato["miles"]:
        texto = texto.str.replace(contrato["miles"], "", regex=False)
    if contrato["decimal"] != ".":
        texto = texto.str.replace(contrato["decimal"], ".", regex=False)
    return pd.to_numeric(texto, errors="coerce")  # lo que no sea un número -> NaN


def limpiar(df: pd.DataFrame, contrato: dict) -> pd.DataFrame:
    df = df.copy()
    df["sku"] = df["sku"].str.strip().str.upper().str.replace(" ", "", regex=False)
    df["descripcion"] = df["descripcion"].str.strip()
    df["moneda"] = df["moneda"].str.strip().str.upper()
    df["precio_coste"] = a_numero(df["precio_coste"], contrato)
    df["stock_disponible"] = a_numero(df["stock_disponible"], contrato)
    df["plazo_entrega_dias"] = a_numero(df["plazo_entrega_dias"], contrato)
    df["fecha_tarifa"] = pd.to_datetime(df["fecha_tarifa"].str.strip(),
                                        format=contrato["formato_fecha"], errors="coerce").dt.date
    return df


def validar(df: pd.DataFrame, contrato: dict, catalogo: dict, tipos_cambio: dict) -> pd.DataFrame:
    """
    Añade una columna 'motivo' con el PRIMER problema encontrado en cada fila.
    Si la fila está bien, motivo = None.
    """
    df = df.copy()
    df["motivo"] = None

    def marcar(condicion, motivo):
        df.loc[condicion & df["motivo"].isna(), "motivo"] = motivo

    marcar(df["sku"] == "", "sku_vacio")
    marcar(~df["sku"].isin(catalogo), "sku_desconocido")
    marcar(df["fecha_tarifa"].isna(), "fecha_invalida")
    marcar(df["moneda"] != contrato["moneda"], "moneda_incorrecta")
    marcar(df["precio_coste"].isna(), "precio_no_numerico")
    marcar(df["precio_coste"] <= 0, "precio_no_positivo")
    marcar(df["stock_disponible"].isna() | (df["stock_disponible"] < 0), "stock_invalido")

    # Conversión a euros con el tipo de cambio de ESE día
    df["tipo_cambio"] = [tipos_cambio.get((f, contrato["moneda"])) for f in df["fecha_tarifa"]]
    marcar(df["tipo_cambio"].isna(), "sin_tipo_cambio")
    df["precio_coste_eur"] = (df["precio_coste"] / df["tipo_cambio"].astype(float)).round(2)

    # Precio anómalo: muy lejos del coste que conocemos del producto (errores de tecleo, etc.)
    coste_conocido = df["sku"].map(catalogo).astype(float)
    ratio = df["precio_coste_eur"] / coste_conocido
    minimo, maximo = RANGO_PRECIO_VALIDO
    marcar((ratio < minimo) | (ratio > maximo), "precio_anomalo")

    # Duplicados: si un SKU sale varias veces, nos quedamos con la ÚLTIMA aparición
    validas = df["motivo"].isna()
    duplicada = df[validas].duplicated(subset=["sku"], keep="last")
    df.loc[duplicada[duplicada].index, "motivo"] = "duplicado"
    return df


# ---------------------------------------------------------------------
# LOAD
# ---------------------------------------------------------------------

def cargar(conn_dw, validas: pd.DataFrame, id_proveedor: int, nombre_fichero: str):
    filas = [
        (r.fecha_tarifa, id_proveedor, r.sku, r.descripcion[:200] or None, r.moneda,
         round(float(r.precio_coste), 2), float(r.tipo_cambio), float(r.precio_coste_eur),
         int(r.stock_disponible),
         None if pd.isna(r.plazo_entrega_dias) else int(r.plazo_entrega_dias),
         nombre_fichero)
        for r in validas.itertuples()
    ]
    with conn_dw.cursor() as cur:
        cur.executemany(
            """INSERT INTO staging.proveedor_tarifa
                   (fecha_tarifa, id_proveedor, sku, descripcion, moneda, precio_coste, tipo_cambio,
                    precio_coste_eur, stock_disponible, plazo_entrega_dias, fichero)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (fecha_tarifa, id_proveedor, sku) DO UPDATE SET
                   descripcion = EXCLUDED.descripcion, moneda = EXCLUDED.moneda,
                   precio_coste = EXCLUDED.precio_coste, tipo_cambio = EXCLUDED.tipo_cambio,
                   precio_coste_eur = EXCLUDED.precio_coste_eur,
                   stock_disponible = EXCLUDED.stock_disponible,
                   plazo_entrega_dias = EXCLUDED.plazo_entrega_dias,
                   fichero = EXCLUDED.fichero, cargado_en = now()""",
            filas,
        )


def guardar_rechazos(conn_dw, id_ejecucion, rechazadas: pd.DataFrame, original: pd.DataFrame, nombre):
    originales = original.set_index("num_fila")
    filas = [
        (id_ejecucion, "proveedores", nombre, int(r.num_fila), r.motivo,
         json.dumps(originales.loc[r.num_fila].to_dict(), ensure_ascii=False))
        for r in rechazadas.itertuples()
    ]
    with conn_dw.cursor() as cur:
        cur.executemany(
            """INSERT INTO etl.rechazo (id_ejecucion, fuente, fichero, num_fila, motivo, datos)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            filas,
        )


def registrar_fichero(conn_dw, nombre, hash_sha, id_ejecucion, estado, total, validas, rechazadas):
    conn_dw.execute(
        """INSERT INTO etl.fichero_procesado (nombre_fichero, hash_sha256, id_ejecucion, estado,
                                              filas_totales, filas_validas, filas_rechazadas)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (nombre, hash_sha, id_ejecucion, estado, total, validas, rechazadas),
    )


# ---------------------------------------------------------------------
# PROCESO COMPLETO
# ---------------------------------------------------------------------

def cargar_referencias(conn_dw):
    """Catálogo {sku: coste €}, proveedores {nombre: id} y tipos de cambio {(fecha, moneda): tasa}."""
    catalogo = dict(conn_dw.execute("SELECT sku, coste FROM staging.oltp_producto").fetchall())
    proveedores = dict(conn_dw.execute("SELECT nombre, id_proveedor FROM staging.oltp_proveedor").fetchall())
    tipos = {(f, m): float(t) for f, m, t in
             conn_dw.execute("SELECT fecha, moneda, tasa FROM staging.tipo_cambio").fetchall()}
    if not catalogo:
        raise RuntimeError("staging.oltp_producto está vacía: ejecuta antes la extracción de la OLTP")
    return catalogo, proveedores, tipos


def procesar_fichero(conn_dw, id_ejecucion, ruta, referencias, resultado):
    catalogo, proveedores, tipos = referencias
    codigo = ruta.stem
    nombre = ruta.relative_to(RAIZ).as_posix()
    hash_sha = hash_fichero(ruta)

    contrato = CONTRATOS_PROVEEDOR.get(codigo)
    if contrato is None:
        resultado.aviso(f"   {nombre}: proveedor desconocido '{codigo}', se ignora")
        return

    original = leer_csv(ruta, contrato)
    revisado = validar(limpiar(original, contrato), contrato, catalogo, tipos)
    validas = revisado[revisado["motivo"].isna()]
    rechazadas = revisado[revisado["motivo"].notna()]
    total = len(revisado)
    pct_rechazo = len(rechazadas) / total if total else 1

    resultado.leidas += total
    guardar_rechazos(conn_dw, id_ejecucion, rechazadas, original, nombre)

    if pct_rechazo > UMBRAL_RECHAZO_FICHERO:
        # "Cortacircuitos": un fichero tan malo probablemente está roto. No cargamos nada.
        resultado.rechazadas += total
        registrar_fichero(conn_dw, nombre, hash_sha, id_ejecucion, "descartado", total, 0, total)
        resultado.aviso(f"   {nombre}: DESCARTADO, {pct_rechazo:.0%} de filas con errores "
                        f"(umbral {UMBRAL_RECHAZO_FICHERO:.0%})")
        return

    cargar(conn_dw, validas, proveedores[contrato["nombre"]], nombre)
    registrar_fichero(conn_dw, nombre, hash_sha, id_ejecucion, "cargado", total, len(validas), len(rechazadas))
    resultado.cargadas += len(validas)
    resultado.rechazadas += len(rechazadas)
    motivos = rechazadas["motivo"].value_counts().to_dict()
    log.info(f"   {nombre}: {len(validas)}/{total} válidas"
             + (f" | rechazos: {motivos}" if motivos else ""))


def ejecutar(conn_dw, id_ejecucion, fecha_proceso, resultado):
    pendientes = ficheros_pendientes(conn_dw, fecha_proceso)
    if not pendientes:
        resultado.aviso("   No hay ficheros nuevos de proveedores")
        return
    log.info(f"   {len(pendientes)} ficheros pendientes")
    referencias = cargar_referencias(conn_dw)

    for ruta in pendientes:
        # SAVEPOINT: si un fichero falla, se deshace solo ese fichero y seguimos con los demás
        try:
            with conn_dw.transaction():
                procesar_fichero(conn_dw, id_ejecucion, ruta, referencias, resultado)
        except Exception as error:  # noqa: BLE001
            resultado.estado = "error"
            resultado.detalle.append(f"{ruta.name}: {error}")
            log.error(f"   {ruta.relative_to(RAIZ).as_posix()}: ERROR {error}")