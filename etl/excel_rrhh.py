"""
excel_rrhh.py -> ETL de los Excel mensuales de Recursos Humanos.

Un Excel hecho a mano NO es una tabla: tiene títulos, celdas combinadas, filas en
blanco, totales, fórmulas, fechas que a veces son texto... Este módulo:

  E: busca en data/landing/rrhh/<AAAA-MM>/ los Excel que aún no se han procesado
     (controlado por su hash, igual que los CSV de proveedores).
  T: 1) BUSCA la fila de cabecera (no da por hecho que esté en la fila 1)
     2) Lee hasta la fila de TOTAL, saltando las filas en blanco
     3) Convierte fechas, horas e importes escritos de cualquier forma
     4) Identifica al empleado por su número o, si falta, por su nombre
     5) Recalcula lo que el Excel trae como fórmula (no se fía de ella)
     6) Valida cada fila y apunta el motivo de las que no pasan
  L: carga "por partición": borra lo que hubiera de ese centro y mes, e inserta lo nuevo.
     Así, si llega un Excel corregido, sustituye entero al anterior (incluidas filas borradas).
"""
import hashlib
import json
import re
import unicodedata
from datetime import date, datetime, time, timedelta

from openpyxl import load_workbook

from configuracion import MIN_FILAS_PARA_UMBRAL, RAIZ, UMBRAL_RECHAZO_FICHERO
from registro import log

CARPETA_RRHH = RAIZ / "data" / "landing" / "rrhh"
EXCEL_EPOCH = datetime(1899, 12, 30)   # el día 0 de las fechas de Excel

TIPOS_AUSENCIA = {
    "vacaciones": "vacaciones", "vac": "vacaciones",
    "baja medica": "baja_medica", "baja": "baja_medica", "it": "baja_medica",
    "asuntos propios": "asuntos_propios", "aapp": "asuntos_propios",
    "permiso": "permiso", "permiso retribuido": "permiso",
}


class FilaInvalida(Exception):
    """Una fila no supera una validación. El mensaje es el motivo del rechazo."""


# ---------------------------------------------------------------------
# Conversión de valores "de Excel"
# ---------------------------------------------------------------------

def normalizar(texto) -> str:
    """'  José   GARCÍA ' -> 'jose garcia' (para comparar nombres escritos de formas distintas)."""
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", t).strip()


def a_fecha(valor) -> date:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, (int, float)) and 20000 < valor < 80000:   # nº de serie de Excel
        return (EXCEL_EPOCH + timedelta(days=int(valor))).date()
    if isinstance(valor, str):
        for formato in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"):
            try:
                return datetime.strptime(valor.strip(), formato).date()
            except ValueError:
                pass
    raise FilaInvalida("fecha_invalida")


def a_hora(valor) -> time:
    if isinstance(valor, time):
        return valor.replace(second=0, microsecond=0)
    if isinstance(valor, datetime):
        return valor.time().replace(second=0, microsecond=0)
    if isinstance(valor, float) and 0 <= valor < 1:                # fracción del día de Excel
        minutos = round(valor * 24 * 60)
        return time(minutos // 60, minutos % 60)
    if isinstance(valor, str):
        # "9:58", "09.58", "9h58", "9h", "9"
        m = re.fullmatch(r"\s*(\d{1,2})\s*(?:[:.h]\s*(\d{2})?)?\s*h?\s*", valor.lower())
        if m and int(m.group(1)) < 24:
            return time(int(m.group(1)), int(m.group(2) or 0))
    raise FilaInvalida("hora_invalida")


def a_importe(valor) -> float:
    """1850.0, '1.850,00 €', '1850,5' -> número."""
    if isinstance(valor, (int, float)):
        return float(valor)
    if isinstance(valor, str):
        texto = valor.replace("€", "").replace(" ", "").replace("\xa0", "")
        texto = texto.replace(".", "").replace(",", ".")
        try:
            return float(texto)
        except ValueError:
            pass
    raise FilaInvalida("importe_invalido")


def a_entero(valor):
    if valor is None or valor == "":
        return None
    try:
        return int(float(valor))
    except (TypeError, ValueError):
        raise FilaInvalida("numero_invalido") from None


# ---------------------------------------------------------------------
# Lectura de la hoja: buscar la cabecera y leer hasta el TOTAL
# ---------------------------------------------------------------------

def buscar_cabecera(ws, columnas: dict, max_filas=20):
    """
    Busca en las primeras filas la que contiene los nombres de columna esperados.
    columnas = {"texto de la cabecera en el Excel": "nombre que usamos nosotros"}
    Devuelve (nº de fila de la cabecera, {nombre nuestro: índice de columna}).
    """
    buscadas = {normalizar(k): v for k, v in columnas.items()}
    for fila in ws.iter_rows(min_row=1, max_row=max_filas):
        encontradas = {buscadas[normalizar(c.value)]: c.column - 1
                       for c in fila if c.value is not None and normalizar(c.value) in buscadas}
        if len(encontradas) == len(buscadas):
            return fila[0].row, encontradas
    raise ValueError(f"No se encuentra la cabecera con las columnas {list(columnas)}")


def leer_filas(ws, fila_cabecera, mapa):
    """Lee las filas de datos como diccionarios. Salta las vacías y para en la de TOTAL."""
    for fila in ws.iter_rows(min_row=fila_cabecera + 1, values_only=True):
        if all(v is None or v == "" for v in fila):
            continue                                           # fila en blanco entre semanas
        primera = fila[0]
        if isinstance(primera, str) and normalizar(primera).startswith("total"):
            break                                              # fila de totales: aquí acaban los datos
        yield {nombre: fila[i] if i < len(fila) else None for nombre, i in mapa.items()}


# ---------------------------------------------------------------------
# Identificación de empleados y centros
# ---------------------------------------------------------------------

def cargar_referencias(conn_dw):
    empleados = conn_dw.execute(
        "SELECT id_empleado, nombre, apellidos, id_ubicacion FROM staging.oltp_empleado").fetchall()
    if not empleados:
        raise RuntimeError("staging.oltp_empleado está vacía: ejecuta antes la extracción de la OLTP")
    por_id = {e[0]: e[3] for e in empleados}
    por_nombre = {}
    for id_emp, nombre, apellidos, id_ubi in empleados:
        por_nombre.setdefault(normalizar(f"{nombre} {apellidos}"), []).append((id_emp, id_ubi))
    centros = {normalizar(n): i for i, n in conn_dw.execute(
        "SELECT id_ubicacion, nombre FROM staging.oltp_ubicacion").fetchall()}
    return {"por_id": por_id, "por_nombre": por_nombre, "centros": centros}


def identificar_empleado(ref, numero, nombre, id_centro=None) -> int:
    """Por nº de empleado si viene y existe; si no, por el nombre completo."""
    numero = a_entero(numero)
    if numero is not None:
        if numero in ref["por_id"]:
            return numero
        raise FilaInvalida("empleado_desconocido")
    candidatos = ref["por_nombre"].get(normalizar(nombre or ""), [])
    if id_centro is not None and len(candidatos) > 1:          # dos personas con el mismo nombre
        candidatos = [c for c in candidatos if c[1] == id_centro]
    if len(candidatos) == 1:
        return candidatos[0][0]
    raise FilaInvalida("empleado_ambiguo" if candidatos else "empleado_desconocido")


def identificar_centro(ref, texto) -> int:
    """'Centro: TechNova Madrid Gran Vía' o un nombre de hoja recortado a 31 caracteres."""
    buscado = normalizar(re.sub(r"(?i)^\s*centro\s*:", "", str(texto)))
    for nombre, id_ubi in ref["centros"].items():
        if nombre == buscado or nombre.startswith(buscado):
            return id_ubi
    raise ValueError(f"Centro desconocido: {texto}")


# ---------------------------------------------------------------------
# Cada tipo de Excel
# ---------------------------------------------------------------------

def mes_del_fichero(ruta) -> date:
    return date.fromisoformat(ruta.parent.name + "-01")


def fin_de_mes(mes: date) -> date:
    return (mes + timedelta(days=32)).replace(day=1) - timedelta(days=1)


def transformar_fichajes(ruta, ref):
    wb = load_workbook(ruta, data_only=True)
    ws = wb.active
    # El centro está en una celda de las primeras filas: "Centro: ..."
    celda_centro = next(c.value for fila in ws.iter_rows(max_row=5) for c in fila
                        if isinstance(c.value, str) and normalizar(c.value).startswith("centro"))
    id_centro = identificar_centro(ref, celda_centro)
    mes = mes_del_fichero(ruta)

    fila_cab, mapa = buscar_cabecera(ws, {
        "Fecha": "fecha", "Nº empleado": "numero", "Empleado": "nombre",
        "Entrada": "entrada", "Salida": "salida", "Pausa (min)": "pausa"})
    validas, rechazos = {}, []
    for n, fila in enumerate(leer_filas(ws, fila_cab, mapa), start=fila_cab + 1):
        try:
            fecha = a_fecha(fila["fecha"])
            if not mes <= fecha <= fin_de_mes(mes):
                raise FilaInvalida("fecha_fuera_del_mes")
            id_emp = identificar_empleado(ref, fila["numero"], fila["nombre"], id_centro)
            if fila["entrada"] is None or fila["salida"] is None:
                raise FilaInvalida("fichaje_incompleto")
            entrada, salida = a_hora(fila["entrada"]), a_hora(fila["salida"])
            pausa = a_entero(fila["pausa"]) or 0
            # La columna "Horas" del Excel es una fórmula: la recalculamos nosotros
            minutos = (salida.hour * 60 + salida.minute) - (entrada.hour * 60 + entrada.minute) - pausa
            if minutos <= 0:
                raise FilaInvalida("salida_antes_de_entrada")
            horas = round(minutos / 60, 2)
            if horas > 14:
                raise FilaInvalida("horas_imposibles")
            clave = (fecha, id_emp)
            if clave in validas:                                     # fila repetida: vale la última
                rechazos.append((validas[clave][0], "duplicado", validas[clave][1]))
            validas[clave] = (n, fila, (fecha, id_emp, id_centro, entrada, salida, pausa, horas))
        except FilaInvalida as error:
            rechazos.append((n, str(error), fila))
    filas = [v[2] for v in validas.values()]
    rechazos = [(n, m, f) for n, m, f in rechazos]
    return {"particion": ("fichaje", id_centro, mes), "filas": filas, "rechazos": rechazos}


def transformar_ausencias(ruta, ref):
    wb = load_workbook(ruta, data_only=True)
    mes = mes_del_fichero(ruta)
    filas, rechazos = {}, []
    for ws in wb.worksheets:                                  # una hoja por centro
        id_centro = identificar_centro(ref, ws.title)
        fila_cab, mapa = buscar_cabecera(ws, {
            "Empleado": "nombre", "Tipo": "tipo", "Desde": "desde", "Hasta": "hasta"})
        for n, fila in enumerate(leer_filas(ws, fila_cab, mapa), start=fila_cab + 1):
            try:
                id_emp = identificar_empleado(ref, None, fila["nombre"], id_centro)
                tipo = TIPOS_AUSENCIA.get(normalizar(fila["tipo"] or ""))
                if tipo is None:
                    raise FilaInvalida("tipo_ausencia_desconocido")
                desde, hasta = a_fecha(fila["desde"]), a_fecha(fila["hasta"])
                if hasta < desde:
                    raise FilaInvalida("fechas_invertidas")
                if hasta < mes or desde > fin_de_mes(mes):
                    raise FilaInvalida("fecha_fuera_del_mes")
                filas[(id_emp, desde)] = (id_emp, tipo, desde, hasta)
            except FilaInvalida as error:
                rechazos.append((n, str(error), dict(fila, hoja=ws.title)))
    return {"particion": ("ausencia", None, mes), "filas": list(filas.values()), "rechazos": rechazos}


def transformar_nominas(ruta, ref):
    wb = load_workbook(ruta, data_only=True)
    ws = wb.active
    mes = mes_del_fichero(ruta)
    fila_cab, mapa = buscar_cabecera(ws, {
        "Nº Empleado": "numero", "Apellidos, Nombre": "nombre", "Salario base": "base",
        "Plus ventas": "plus", "Horas extra": "horas_extra", "Importe horas extra": "importe_hx",
        "Total devengado": "devengado", "SS empresa": "ss", "Coste total": "coste"})
    filas, rechazos = {}, []
    for n, fila in enumerate(leer_filas(ws, fila_cab, mapa), start=fila_cab + 1):
        try:
            # "García López, María" -> "María García López"
            apellidos, _, nombre = str(fila["nombre"] or "").partition(",")
            id_emp = identificar_empleado(ref, fila["numero"], f"{nombre} {apellidos}")
            base, plus, importe_hx = a_importe(fila["base"]), a_importe(fila["plus"]), a_importe(fila["importe_hx"])
            devengado, ss, coste = a_importe(fila["devengado"]), a_importe(fila["ss"]), a_importe(fila["coste"])
            horas_extra = a_importe(fila["horas_extra"])
            # Comprobamos que los importes cuadran entre sí
            if abs(base + plus + importe_hx - devengado) > 0.05 or abs(devengado + ss - coste) > 0.05:
                raise FilaInvalida("importes_no_cuadran")
            filas[id_emp] = (mes, id_emp, base, plus, horas_extra, importe_hx, devengado, ss, coste)
        except FilaInvalida as error:
            rechazos.append((n, str(error), fila))
    return {"particion": ("nomina", None, mes), "filas": list(filas.values()), "rechazos": rechazos}


TRANSFORMADORES = {"fichajes": transformar_fichajes, "ausencias": transformar_ausencias,
                   "nominas": transformar_nominas}


# ---------------------------------------------------------------------
# LOAD: carga por partición
# ---------------------------------------------------------------------

def cargar(conn_dw, resultado_fichero, nombre_fichero):
    tipo, id_centro, mes = resultado_fichero["particion"]
    filas = resultado_fichero["filas"]
    siguiente_mes = fin_de_mes(mes) + timedelta(days=1)
    with conn_dw.cursor() as cur:
        if tipo == "fichaje":
            cur.execute("DELETE FROM staging.rrhh_fichaje WHERE id_ubicacion = %s AND fecha >= %s AND fecha < %s",
                        (id_centro, mes, siguiente_mes))
            cur.executemany(
                """INSERT INTO staging.rrhh_fichaje
                       (fecha, id_empleado, id_ubicacion, entrada, salida, pausa_min, horas, fichero)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                [f + (nombre_fichero,) for f in filas])
        elif tipo == "ausencia":
            cur.execute("DELETE FROM staging.rrhh_ausencia WHERE desde >= %s AND desde < %s", (mes, siguiente_mes))
            cur.executemany(
                "INSERT INTO staging.rrhh_ausencia (id_empleado, tipo, desde, hasta, fichero) VALUES (%s, %s, %s, %s, %s)",
                [f + (nombre_fichero,) for f in filas])
        else:
            cur.execute("DELETE FROM staging.rrhh_nomina WHERE mes = %s", (mes,))
            cur.executemany(
                """INSERT INTO staging.rrhh_nomina
                       (mes, id_empleado, salario_base, plus_ventas, horas_extra, importe_horas_extra,
                        total_devengado, ss_empresa, coste_total, fichero)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                [f + (nombre_fichero,) for f in filas])


def guardar_rechazos(conn_dw, id_ejecucion, nombre_fichero, rechazos):
    with conn_dw.cursor() as cur:
        cur.executemany(
            """INSERT INTO etl.rechazo (id_ejecucion, fuente, fichero, num_fila, motivo, datos)
               VALUES (%s, 'rrhh', %s, %s, %s, %s)""",
            [(id_ejecucion, nombre_fichero, n, motivo, json.dumps(fila, default=str, ensure_ascii=False))
             for n, motivo, fila in rechazos])


# ---------------------------------------------------------------------
# PROCESO COMPLETO
# ---------------------------------------------------------------------

def ficheros_pendientes(conn_dw, fecha_proceso: date):
    procesados = set(conn_dw.execute("SELECT nombre_fichero, hash_sha256 FROM etl.fichero_procesado").fetchall())
    mes_actual = fecha_proceso.replace(day=1)
    orden = {"fichajes": 0, "ausencias": 1, "nominas": 2}
    pendientes = []
    for ruta in CARPETA_RRHH.glob("*/*.xlsx"):
        try:
            mes = mes_del_fichero(ruta)
        except ValueError:
            log.warning(f"   Carpeta con nombre no válido, se ignora: {ruta.parent.name}")
            continue
        if mes > mes_actual or ruta.name.startswith("~$"):         # ~$ = fichero temporal de Excel abierto
            continue
        nombre = ruta.relative_to(RAIZ).as_posix()
        hash_sha = hashlib.sha256(ruta.read_bytes()).hexdigest()
        if (nombre, hash_sha) not in procesados:
            pendientes.append((mes, orden.get(ruta.name.split("_")[0], 9), ruta, nombre, hash_sha))
    return sorted(pendientes)


def ejecutar(conn_dw, id_ejecucion, fecha_proceso, resultado):
    pendientes = ficheros_pendientes(conn_dw, fecha_proceso)
    if not pendientes:
        log.info("   No hay Excel nuevos de RRHH")
        return
    log.info(f"   {len(pendientes)} Excel pendientes")
    ref = cargar_referencias(conn_dw)

    for _, _, ruta, nombre, hash_sha in pendientes:
        tipo = ruta.name.split("_")[0]
        try:
            with conn_dw.transaction():                       # SAVEPOINT: un fichero malo no afecta a los demás
                if tipo not in TRANSFORMADORES:
                    resultado.aviso(f"   {nombre}: tipo de Excel desconocido, se ignora")
                    continue
                res = TRANSFORMADORES[tipo](ruta, ref)
                validas, malas = len(res["filas"]), len(res["rechazos"])
                total = validas + malas
                guardar_rechazos(conn_dw, id_ejecucion, nombre, res["rechazos"])
                descartar = total and malas / total > UMBRAL_RECHAZO_FICHERO and total >= MIN_FILAS_PARA_UMBRAL
                if not descartar:
                    cargar(conn_dw, res, nombre)
                conn_dw.execute(
                    """INSERT INTO etl.fichero_procesado (nombre_fichero, hash_sha256, id_ejecucion, estado,
                                                          filas_totales, filas_validas, filas_rechazadas)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (nombre, hash_sha, id_ejecucion, "descartado" if descartar else "cargado",
                     total, 0 if descartar else validas, total if descartar else malas))
            resultado.leidas += total
            if descartar:
                resultado.rechazadas += total
                resultado.aviso(f"   {nombre}: DESCARTADO, {malas / total:.0%} de filas con errores")
                continue
            resultado.cargadas += validas
            resultado.rechazadas += malas
            motivos = {}
            for _, motivo, _ in res["rechazos"]:
                motivos[motivo] = motivos.get(motivo, 0) + 1
            log.info(f"   {nombre}: {validas}/{total} válidas" + (f" | rechazos: {motivos}" if motivos else ""))
        except Exception as error:  # noqa: BLE001
            resultado.estado = "error"
            resultado.detalle.append(f"{ruta.name}: {error}")
            log.error(f"   {nombre}: ERROR {error}")