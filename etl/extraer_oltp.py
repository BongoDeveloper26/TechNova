"""
extraer_oltp.py -> Copia las tablas de la OLTP a staging.oltp_<tabla> en el DW.

Esto es la parte "EL" de un ELT: Extraer y Cargar tal cual.
La Transformación se hará después dentro del DW con dbt (Fase 5).

Técnicas usadas:
  - COPY: la forma más rápida de mover datos en PostgreSQL (mucho más que INSERT fila a fila).
  - Tabla temporal + UPSERT (INSERT ... ON CONFLICT DO UPDATE) para las cargas incrementales.
  - Marcas de agua (etl.watermark) para saber hasta dónde se cargó la última vez.
"""
from psycopg import sql

from configuracion import ESTRATEGIAS_OLTP
from registro import log


# ---------------------------------------------------------------------
# Estructura: crear staging.oltp_<tabla> copiando las columnas de la OLTP
# ---------------------------------------------------------------------

def leer_estructura(conn_oltp, tabla):
    """Devuelve ([(columna, tipo)], [columnas de la PK]) de oltp.<tabla>."""
    columnas = conn_oltp.execute(
        """SELECT a.attname, format_type(a.atttypid, a.atttypmod)
           FROM pg_attribute a
           WHERE a.attrelid = %s::regclass AND a.attnum > 0 AND NOT a.attisdropped
           ORDER BY a.attnum""",
        (f"oltp.{tabla}",),
    ).fetchall()
    pk = [fila[0] for fila in conn_oltp.execute(
        """SELECT a.attname
           FROM pg_index i
           JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
           WHERE i.indrelid = %s::regclass AND i.indisprimary
           ORDER BY array_position(i.indkey::int2[], a.attnum)""",
        (f"oltp.{tabla}",),
    ).fetchall()]
    return columnas, pk


def crear_tabla_staging(conn_dw, tabla, columnas, pk):
    """En staging no hay FK ni CHECK: guardamos lo que hay en la fuente, tal cual."""
    definicion = sql.SQL(", ").join(
        [sql.SQL("{} {}").format(sql.Identifier(nombre), sql.SQL(tipo)) for nombre, tipo in columnas]
        + [sql.SQL("_cargado_en TIMESTAMPTZ NOT NULL DEFAULT now()")]
        + [sql.SQL("PRIMARY KEY ({})").format(sql.SQL(", ").join(map(sql.Identifier, pk)))]
    )
    conn_dw.execute(sql.SQL("CREATE TABLE IF NOT EXISTS staging.{} ({})").format(
        sql.Identifier(f"oltp_{tabla}"), definicion))


# ---------------------------------------------------------------------
# Movimiento de datos con COPY
# ---------------------------------------------------------------------

def copiar(conn_oltp, conn_dw, consulta_origen, tabla_destino, columnas):
    """COPY (SELECT ...) TO STDOUT en la OLTP  ->  COPY tabla FROM STDIN en el DW."""
    lista = sql.SQL(", ").join(map(sql.Identifier, columnas))
    destino = sql.SQL("COPY {} ({}) FROM STDIN").format(tabla_destino, lista)
    origen = sql.SQL("COPY ({}) TO STDOUT").format(consulta_origen)

    with conn_oltp.cursor() as cur_in, conn_dw.cursor() as cur_out:
        with cur_in.copy(origen) as copia_in, cur_out.copy(destino) as copia_out:
            for bloque in copia_in:
                copia_out.write(bloque)
        return cur_out.rowcount


def upsert_desde_temporal(conn_dw, tabla, columnas, pk):
    """Pasa las filas de la tabla temporal a staging: inserta las nuevas y actualiza las que ya estaban."""
    no_pk = [c for c in columnas if c not in pk]
    conn_dw.execute(sql.SQL("""
        INSERT INTO staging.{tabla} ({cols})
        SELECT {cols} FROM tmp_carga
        ON CONFLICT ({pk}) DO UPDATE SET {sets}, _cargado_en = now()
    """).format(
        tabla=sql.Identifier(f"oltp_{tabla}"),
        cols=sql.SQL(", ").join(map(sql.Identifier, columnas)),
        pk=sql.SQL(", ").join(map(sql.Identifier, pk)),
        sets=sql.SQL(", ").join(
            sql.SQL("{c} = EXCLUDED.{c}").format(c=sql.Identifier(c)) for c in no_pk),
    ))


# ---------------------------------------------------------------------
# Marcas de agua
# ---------------------------------------------------------------------

def leer_watermark(conn_dw, tabla):
    fila = conn_dw.execute("SELECT valor FROM etl.watermark WHERE tabla = %s", (tabla,)).fetchone()
    return fila[0] if fila else None


def guardar_watermark(conn_dw, tabla, columna):
    nuevo = conn_dw.execute(sql.SQL("SELECT MAX({})::text FROM staging.{}").format(
        sql.Identifier(columna), sql.Identifier(f"oltp_{tabla}"))).fetchone()[0]
    if nuevo is not None:
        conn_dw.execute(
            """INSERT INTO etl.watermark (tabla, columna, valor) VALUES (%s, %s, %s)
               ON CONFLICT (tabla) DO UPDATE SET valor = EXCLUDED.valor, actualizado_en = now()""",
            (tabla, columna, nuevo),
        )
    return nuevo


# ---------------------------------------------------------------------
# Carga de una tabla según su estrategia
# ---------------------------------------------------------------------

def cargar_tabla(conn_oltp, conn_dw, tabla, estrategia):
    columnas_tipos, pk = leer_estructura(conn_oltp, tabla)
    columnas = [c for c, _ in columnas_tipos]
    crear_tabla_staging(conn_dw, tabla, columnas_tipos, pk)
    origen = sql.SQL("SELECT {} FROM oltp.{}").format(
        sql.SQL(", ").join(map(sql.Identifier, columnas)), sql.Identifier(tabla))
    tipo = estrategia["tipo"]

    if tipo == "completa":
        conn_dw.execute(sql.SQL("TRUNCATE staging.{}").format(sql.Identifier(f"oltp_{tabla}")))
        filas = copiar(conn_oltp, conn_dw, origen, sql.Identifier("staging", f"oltp_{tabla}"), columnas)
        return filas, "completa"

    columna = estrategia["columna"]
    marca = leer_watermark(conn_dw, tabla)

    if marca is None:
        filtro, descripcion = sql.SQL(""), "primera carga (completa)"
    elif tipo == "incremental":
        filtro = sql.SQL(" WHERE {} > {}").format(sql.Identifier(columna), sql.Literal(marca))
        descripcion = f"{columna} > {marca}"
    else:  # ventana
        filtro = sql.SQL(" WHERE {} >= {}::timestamp - {} * INTERVAL '1 day'").format(
            sql.Identifier(columna), sql.Literal(marca), sql.Literal(estrategia["dias"]))
        descripcion = f"{columna} >= {marca} - {estrategia['dias']} días"

    conn_dw.execute(sql.SQL(
        "CREATE TEMP TABLE tmp_carga (LIKE staging.{} INCLUDING DEFAULTS) ON COMMIT DROP").format(
        sql.Identifier(f"oltp_{tabla}")))
    filas = copiar(conn_oltp, conn_dw, origen + filtro, sql.Identifier("tmp_carga"), columnas)
    upsert_desde_temporal(conn_dw, tabla, columnas, pk)
    conn_dw.execute("DROP TABLE tmp_carga")
    nueva_marca = guardar_watermark(conn_dw, tabla, columna)
    return filas, f"{descripcion} -> nueva marca {nueva_marca}"


def ejecutar(conn_oltp, conn_dw, resultado):
    for tabla, estrategia in ESTRATEGIAS_OLTP.items():
        filas, descripcion = cargar_tabla(conn_oltp, conn_dw, tabla, estrategia)
        resultado.leidas += filas
        resultado.cargadas += filas
        log.info(f"   {tabla:<20} {filas:>7} filas  ({descripcion})")