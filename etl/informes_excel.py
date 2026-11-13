"""
informes_excel.py -> Genera los informes mensuales en Excel a partir del data warehouse.

Es el camino CONTRARIO a excel_rrhh.py: en vez de leer Excel desordenados,
escribe Excel limpios y profesionales, listos para mandar por correo.

Cada mes genera, en informes/<AAAA-MM>/:

  informe_tienda_<tienda>_<AAAA-MM>.xlsx  (uno por tienda, para su encargado)
      Portada              -> cuadro de mando: 8 tarjetas de indicadores, 4 gráficos y las claves del mes
      Indicadores          -> el mes frente al anterior, al mismo mes del año pasado y al objetivo (semáforos)
      Objetivos            -> objetivos y parámetros EDITABLES (celdas amarillas): todo el libro se recalcula
      Vendedores           -> ranking, comisiones y bonus calculados con fórmulas
      Ventas diarias       -> media móvil, acumulado y ritmo frente al objetivo
      Día de la semana     -> qué días se vende más (SUMIFS / COUNTIFS sobre las ventas diarias)
      Top productos        -> los 10 más vendidos y cuánto concentran (gráfico de Pareto)
      Comparativa tiendas  -> la tienda frente al resto de la cadena, resaltada

  informe_rrhh_<AAAA-MM>.xlsx  (para Recursos Humanos)
      Portada              -> cuadro de mando del mes con variaciones
      Centros              -> indicadores por centro con alertas según un umbral editable
      Ficha de centro      -> SELECTOR: eliges un centro en el desplegable y la hoja entera cambia
      Horas extra          -> conciliación de horas fichadas frente a lo pagado en nómina
      Ausencias            -> detalle del mes y matriz centro x tipo de ausencia
      Evolución            -> últimos 12 meses (todo con fórmulas sobre la hoja Datos)
      Parámetros, Datos    -> valores editables y datos de origen

La idea clave: los valores derivados (ticket medio, variaciones, cumplimientos, comisiones,
acumulados, rankings, totales...) son FÓRMULAS de Excel, no números. Si alguien cambia un
objetivo o un dato, el informe entero se recalcula, como uno hecho a mano por un analista.

Uso:
    python etl/informes_excel.py --mes 2025-12
"""
import argparse
import re
import unicodedata
from datetime import date, timedelta

from openpyxl import Workbook
from openpyxl.formatting.rule import (CellIsRule, ColorScaleRule, DataBarRule, FormulaRule,
                                      IconSetRule)
from openpyxl.styles import Alignment, Font
from openpyxl.worksheet.datavalidation import DataValidation

import excel_estilos as e
from configuracion import RAIZ
from conexiones import conectar_dw

CARPETA_INFORMES = RAIZ / "informes"
MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto",
         "Septiembre", "Octubre", "Noviembre", "Diciembre"]
DIAS_SEMANA = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
TIPOS_AUSENCIA = {"vacaciones": "Vacaciones", "baja_medica": "Baja médica", "asuntos_propios": "Asuntos propios"}


def codigo(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")


def mes_anterior(mes: date, n: int = 1) -> date:
    for _ in range(n):
        mes = (mes - timedelta(days=1)).replace(day=1)
    return mes


def fin_de_mes(mes: date) -> date:
    return (mes + timedelta(days=32)).replace(day=1) - timedelta(days=1)


def nombre_mes(mes: date) -> str:
    return f"{MESES[mes.month - 1]} {mes.year}"


def texto_excel(texto: str) -> str:
    """Un texto dentro de una fórmula va entre comillas dobles (y las comillas se duplican)."""
    return '"' + texto.replace('"', '""') + '"'


# =====================================================================
#  INFORME DE TIENDA
# =====================================================================

# Indicadores de la hoja "Indicadores": (clave, nombre, formato, ¿bueno si sube?, fórmula)
# - fórmula None -> dato que viene del data warehouse
# - fórmula con {clave} -> se calcula en Excel a partir de otros indicadores de la misma columna
# - ¿bueno si sube? None -> neutro (sin colores)
INDICADORES = [
    ("ventas", "Ventas", e.EUROS_ENTERO, True, None),
    ("pedidos", "Pedidos", e.ENTERO, True, None),
    ("ticket", "Ticket medio", e.EUROS, True, "=IF({pedidos}=0,0,{ventas}/{pedidos})"),
    ("unidades", "Unidades vendidas", e.ENTERO, True, None),
    ("uds_pedido", "Unidades por pedido", "0.00", True, "=IF({pedidos}=0,0,{unidades}/{pedidos})"),
    ("devuelto", "Devoluciones", e.EUROS_ENTERO, False, None),
    ("tasa_dev", "Tasa de devolución", e.PORCENTAJE, False, "=IF({ventas}=0,0,{devuelto}/{ventas})"),
    ("horas", "Horas trabajadas", e.ENTERO, None, None),
    ("ventas_hora", "Ventas por hora trabajada", e.EUROS, True, "=IF({horas}=0,0,{ventas}/{horas})"),
    ("coste", "Coste de personal", e.EUROS_ENTERO, False, None),
    ("coste_ventas", "Coste de personal / ventas", e.PORCENTAJE, False, "=IF({ventas}=0,0,{coste}/{ventas})"),
    ("absentismo", "Absentismo", e.PORCENTAJE, False, None),
]
FILA_IND = {clave: 7 + i for i, (clave, *_resto) in enumerate(INDICADORES)}   # fila de cada indicador

# Objetivos editables: (clave, tipo, cómo se calcula el valor propuesto)
#   mínimo -> hay que llegar (ventas...)   máximo -> no hay que pasarse (costes, absentismo...)
OBJETIVOS = [
    ("ventas", "Mínimo", 1.08, "+8 %"),
    ("pedidos", "Mínimo", 1.05, "+5 %"),
    ("ticket", "Mínimo", None, "objetivo de ventas / objetivo de pedidos"),
    ("ventas_hora", "Mínimo", 1.05, "+5 %"),
    ("tasa_dev", "Máximo", 0.90, "-10 %"),
    ("coste_ventas", "Máximo", 0.95, "-5 %"),
    ("absentismo", "Máximo", None, "política de la empresa"),
]
FILA_OBJ = {clave: 7 + i for i, (clave, *_resto) in enumerate(OBJETIVOS)}


def kpis_tienda(conn, id_tienda, mes):
    """Los datos 'en bruto' de una tienda en un mes (los derivados se calculan en Excel)."""
    ventas, pedidos, unidades, devuelto = conn.execute("""
        SELECT COALESCE(SUM(importe_neto), 0), COUNT(DISTINCT id_pedido),
               COALESCE(SUM(cantidad), 0), COALESCE(SUM(importe_devuelto), 0)
        FROM marts.fct_ventas
        WHERE canal = 'tienda' AND id_ubicacion = %s AND dia BETWEEN %s AND %s
    """, (id_tienda, mes, fin_de_mes(mes))).fetchone()
    horas, coste, absentismo = conn.execute("""
        SELECT horas, coste_personal, absentismo FROM marts.rpt_rrhh_centro_mes
        WHERE id_ubicacion = %s AND mes = %s
    """, (id_tienda, mes)).fetchone() or (0, 0, 0)
    return {"ventas": float(ventas), "pedidos": int(pedidos), "unidades": int(unidades),
            "devuelto": float(devuelto), "horas": float(horas or 0), "coste": float(coste or 0),
            "absentismo": float(absentismo or 0)}


def derivados(k):
    """Los mismos cálculos que hace Excel, para proponer objetivos desde Python."""
    def div(a, b):
        return a / b if b else 0
    return {**k, "ticket": div(k["ventas"], k["pedidos"]), "uds_pedido": div(k["unidades"], k["pedidos"]),
            "tasa_dev": div(k["devuelto"], k["ventas"]), "ventas_hora": div(k["ventas"], k["horas"]),
            "coste_ventas": div(k["coste"], k["ventas"])}


def datos_tienda(conn, id_tienda, mes):
    fin = fin_de_mes(mes)
    historico = [derivados(kpis_tienda(conn, id_tienda, mes_anterior(mes, n))) for n in (1, 2, 3)]
    return {
        "actual": kpis_tienda(conn, id_tienda, mes),
        "anterior": kpis_tienda(conn, id_tienda, mes_anterior(mes)),
        "anio_anterior": kpis_tienda(conn, id_tienda, mes.replace(year=mes.year - 1)),
        "ultimos_3": historico,
        "categorias": conn.execute("""
            SELECT p.categoria, ROUND(SUM(v.importe_neto), 2)
            FROM marts.fct_ventas v JOIN marts.dim_producto p USING (id_producto)
            WHERE v.canal = 'tienda' AND v.id_ubicacion = %s AND v.dia BETWEEN %s AND %s
            GROUP BY 1 ORDER BY 2 DESC
        """, (id_tienda, mes, fin)).fetchall(),
        "vendedores": conn.execute("""
            SELECT r.empleado, r.dias_trabajados, r.horas, r.horas_extra, r.pedidos, r.ventas, r.coste_total
            FROM marts.rpt_productividad_vendedor r
            JOIN marts.dim_ubicacion u ON u.ubicacion = r.tienda
            WHERE u.id_ubicacion = %s AND r.mes = %s
            ORDER BY r.ventas DESC
        """, (id_tienda, mes)).fetchall(),
        "diario": conn.execute("""
            SELECT f.fecha, f.nombre_dia, COUNT(DISTINCT v.id_pedido), COALESCE(SUM(v.importe_neto), 0)
            FROM marts.dim_fecha f
            LEFT JOIN marts.fct_ventas v
                   ON v.id_fecha = f.id_fecha AND v.canal = 'tienda' AND v.id_ubicacion = %s
            WHERE f.fecha BETWEEN %s AND %s
            GROUP BY f.fecha, f.nombre_dia ORDER BY f.fecha
        """, (id_tienda, mes, fin)).fetchall(),
        "productos": conn.execute("""
            SELECT p.producto, p.marca, p.categoria, SUM(v.cantidad), ROUND(SUM(v.importe_neto), 2)
            FROM marts.fct_ventas v JOIN marts.dim_producto p USING (id_producto)
            WHERE v.canal = 'tienda' AND v.id_ubicacion = %s AND v.dia BETWEEN %s AND %s
            GROUP BY 1, 2, 3 ORDER BY 5 DESC LIMIT 10
        """, (id_tienda, mes, fin)).fetchall(),
    }


def datos_cadena(conn, mes):
    """Todas las tiendas en el mes (para la hoja de comparativa)."""
    return conn.execute("""
        SELECT u.ubicacion,
               COALESCE(SUM(v.importe_neto), 0), COUNT(DISTINCT v.id_pedido),
               COALESCE(MAX(r.horas), 0), COALESCE(MAX(r.coste_personal), 0)
        FROM marts.dim_ubicacion u
        LEFT JOIN marts.fct_ventas v
               ON v.id_ubicacion = u.id_ubicacion AND v.canal = 'tienda' AND v.dia BETWEEN %s AND %s
        LEFT JOIN marts.rpt_rrhh_centro_mes r ON r.id_ubicacion = u.id_ubicacion AND r.mes = %s
        WHERE u.tipo = 'tienda'
        GROUP BY u.ubicacion
    """, (mes, fin_de_mes(mes), mes)).fetchall()


# ---------------------------------------------------------------------
# Hojas del informe de tienda
# ---------------------------------------------------------------------

def ref_ind(clave, columna="B"):
    """Celda de un indicador en la hoja Indicadores, p. ej. Indicadores!$B$7."""
    return f"Indicadores!${columna}${FILA_IND[clave]}"


def hoja_indicadores(wb, tienda, mes, d):
    ws = wb.create_sheet("Indicadores")
    ws.sheet_properties.tabColor = e.AZUL
    ws.sheet_view.showGridLines = False
    e.banda_titulo(ws, "Indicadores del mes", f"{tienda}  ·  {nombre_mes(mes)}", 12)

    columnas = ["Indicador", "Este mes", "Mes anterior", "Variación mensual",
                f"{MESES[mes.month - 1]} {mes.year - 1}", "Variación anual", "Objetivo", "Cumplimiento"]
    filas = []
    for clave, nombre, _formato, _bueno, formula in INDICADORES:
        valores = []
        for col, origen in (("B", "actual"), ("C", "anterior"), ("E", "anio_anterior")):
            if formula:
                valores.append(formula.format(**{k: f"{col}{FILA_IND[k]}" for k in FILA_IND}))
            else:
                valores.append(d[origen][clave])
        objetivo = f"=Objetivos!$D${FILA_OBJ[clave]}" if clave in FILA_OBJ else None
        if clave in FILA_OBJ:
            minimo = OBJETIVOS[[o[0] for o in OBJETIVOS].index(clave)][1] == "Mínimo"
            # Cumplimiento > 100 % es bueno en los dos casos: en los "máximos" se invierte la división
            cumplimiento = '=IF(OR(G{r}=0,B{r}=0),"",B{r}/G{r})' if minimo else '=IF(OR(G{r}=0,B{r}=0),"",G{r}/B{r})'
        else:
            cumplimiento = None
        filas.append([nombre, valores[0], valores[1], '=IF(C{r}=0,"",B{r}/C{r}-1)',
                      valores[2], '=IF(E{r}=0,"",B{r}/E{r}-1)', objetivo, cumplimiento])
    primera, ultima = e.escribir_tabla(ws, 6, columnas, filas, "Indicadores", {3: e.VARIACION, 5: e.VARIACION,
                                                                               7: e.PORCENTAJE})
    # Cada fila con su propio formato numérico
    for clave, _nombre, formato, bueno, _f in INDICADORES:
        r = FILA_IND[clave]
        for col in "BCEG":
            ws[f"{col}{r}"].number_format = formato
        ws[f"A{r}"].font = Font(bold=True)
        if bueno is not None:
            bien, mal = (e.FUENTE_VERDE, e.FUENTE_ROJA) if bueno else (e.FUENTE_ROJA, e.FUENTE_VERDE)
            for col in "DF":
                ws.conditional_formatting.add(f"{col}{r}", CellIsRule(operator="greaterThan", formula=["0.0005"], font=bien))
                ws.conditional_formatting.add(f"{col}{r}", CellIsRule(operator="lessThan", formula=["-0.0005"], font=mal))
    # Semáforo de cumplimiento: verde desde el 100 %, ámbar desde el 90 %, rojo por debajo
    ws.conditional_formatting.add(f"H{primera}:H{ultima}",
                                  IconSetRule("3TrafficLights1", "num", [0, 0.9, 1], showValue=True))
    e.nota(ws, f"A{ultima + 2}", "Variaciones en verde cuando mejoran y en rojo cuando empeoran "
                                 "(en costes, devoluciones y absentismo, bajar es mejorar).")
    e.nota(ws, f"A{ultima + 3}", "Cumplimiento: semáforo verde desde el 100 %, ámbar desde el 90 %. "
                                 "Los objetivos se cambian en la hoja Objetivos.")

    # Ventas por categoría, a la derecha (alimenta el gráfico de anillo de la portada)
    filas_cat = [[c, float(v), "=IF(SUM($K$7:$K${fin})=0,0,K{{r}}/SUM($K$7:$K${fin}))".format(
        fin=6 + max(len(d["categorias"]), 1))] for c, v in d["categorias"]]
    e.escribir_tabla(ws, 6, ["Categoría", "Ventas", "% del total"], filas_cat, "Categorias",
                     {1: e.EUROS_ENTERO, 2: e.PORCENTAJE}, columna=10, estilo="TableStyleMedium9")
    e.anchos(ws, {"A": 30, "B": 14, "C": 14, "D": 13, "E": 14, "F": 13, "G": 14, "H": 14,
                  "I": 3, "J": 20, "K": 13, "L": 11})
    ws.freeze_panes = "B7"
    e.preparar_impresion(ws, f"Indicadores · {tienda}")
    return len(d["categorias"])


def referencia_objetivo(d, clave):
    """Base para proponer el objetivo: el mismo mes del año pasado o, si no hay, la media de los 3 anteriores."""
    anio = derivados(d["anio_anterior"])
    if anio["ventas"] > 0 and (clave not in ("ventas_hora", "coste_ventas") or anio["horas"] > 0):
        return anio[clave], "mismo mes del año anterior"
    valores = [h[clave] for h in d["ultimos_3"] if h[clave]]
    if valores:
        return sum(valores) / len(valores), "media de los 3 meses anteriores"
    return derivados(d["actual"])[clave], "mes actual (no hay histórico)"


def hoja_objetivos(wb, tienda, mes, d):
    ws = wb.create_sheet("Objetivos")
    ws.sheet_properties.tabColor = "FFC000"
    ws.sheet_view.showGridLines = False
    e.banda_titulo(ws, "Objetivos y parámetros", f"{tienda}  ·  {nombre_mes(mes)}", 7)
    ws["A5"] = "Las celdas amarillas se pueden cambiar. Al hacerlo se recalculan los cumplimientos, " \
               "el ritmo de ventas, las comisiones y la portada."
    ws["A5"].font = Font(bold=True, color=e.AZUL)

    columnas = ["Indicador", "Referencia", "De dónde sale la referencia", "Objetivo", "Tipo de objetivo"]
    for c, titulo in enumerate(columnas, start=1):
        celda = ws.cell(6, c, titulo)
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = e.relleno(e.AZUL_OSCURO)
        celda.alignment = Alignment(vertical="center")
    ws.row_dimensions[6].height = 24
    nombres = {clave: nombre for clave, nombre, *_ in INDICADORES}
    formatos = {clave: formato for clave, _n, formato, *_ in INDICADORES}
    for clave, tipo, factor, explicacion in OBJETIVOS:
        r = FILA_OBJ[clave]
        ws.cell(r, 1, nombres[clave]).font = Font(bold=True)
        ws.cell(r, 5, tipo)
        if clave == "ticket":
            ws.cell(r, 2, "-")
            ws.cell(r, 3, "Se calcula: objetivo de ventas / objetivo de pedidos")
            ws.cell(r, 4, f"=IF(D{FILA_OBJ['pedidos']}=0,0,D{FILA_OBJ['ventas']}/D{FILA_OBJ['pedidos']})")
            ws.cell(r, 4).number_format = formatos[clave]
            ws.cell(r, 4).font = Font(bold=True, color=e.GRIS_TEXTO)
        elif clave == "absentismo":
            ws.cell(r, 2, "-")
            ws.cell(r, 3, "Política de la empresa")
            e.celda_editable(ws, f"D{r}", 0.03, formatos[clave])
        else:
            base, origen = referencia_objetivo(d, clave)
            ws.cell(r, 2, base).number_format = formatos[clave]
            ws.cell(r, 3, f"{origen.capitalize()} {explicacion}")
            redondeo = 0 if formatos[clave] in (e.EUROS_ENTERO, e.ENTERO) else 4
            e.celda_editable(ws, f"D{r}", round(base * factor, redondeo), formatos[clave])
        for c in range(1, 6):
            ws.cell(r, c).border = e.Border(bottom=e.LINEA_FINA)
    e.nombre_definido(wb, "ObjetivoVentas", "Objetivos", f"D{FILA_OBJ['ventas']}")

    # Parámetros de la retribución variable de los vendedores
    fila = max(FILA_OBJ.values()) + 3
    e.titulo_seccion(ws, f"A{fila}", "Retribución variable de los vendedores", 5)
    ws.cell(fila + 1, 1, "Comisión sobre las ventas")
    e.celda_editable(ws, f"D{fila + 1}", 0.01, "0.0%")
    ws.cell(fila + 2, 1, "Bonus si supera la media de ventas por hora de la tienda")
    e.celda_editable(ws, f"D{fila + 2}", 150, e.EUROS_ENTERO)
    e.nombre_definido(wb, "ComisionVentas", "Objetivos", f"D{fila + 1}")
    e.nombre_definido(wb, "BonusVentasHora", "Objetivos", f"D{fila + 2}")
    e.nota(ws, f"A{fila + 4}", "La hoja está protegida (sin contraseña) para no borrar fórmulas por error: "
                               "solo se pueden editar las celdas amarillas.")
    e.anchos(ws, {"A": 52, "B": 16, "C": 52, "D": 16, "E": 18})
    e.proteger(ws)
    e.preparar_impresion(ws, f"Objetivos · {tienda}")


def hoja_vendedores(wb, tienda, d):
    ws = wb.create_sheet("Vendedores")
    ws.sheet_properties.tabColor = e.AZUL
    n = len(d["vendedores"])
    t = n + 2   # fila de totales (la tabla empieza en la fila 1)
    columnas = ["Vendedor", "Días trabajados", "Horas", "Horas extra", "Pedidos", "Ventas",
                "Ventas por hora", "Coste empresa", "Ventas por € de coste", "Ranking",
                "Comisión", "Bonus", "Retribución variable"]
    filas = [[nombre, dias, float(horas), float(hx), pedidos, float(ventas),
              "=IF(C{r}=0,0,F{r}/C{r})", float(coste or 0), "=IF(H{r}=0,0,F{r}/H{r})",
              f"=RANK(G{{r}},$G$2:$G${n + 1})",
              "=F{r}*ComisionVentas", f"=IF(G{{r}}>$G${t},BonusVentasHora,0)", "=K{r}+L{r}"]
             for nombre, dias, horas, hx, pedidos, ventas, coste in d["vendedores"]]
    primera, ultima = e.escribir_tabla(ws, 1, columnas, filas, "Vendedores",
                                       {2: e.DECIMAL, 3: e.DECIMAL, 5: e.EUROS_ENTERO, 6: e.EUROS,
                                        7: e.EUROS_ENTERO, 8: "0.00", 10: e.EUROS, 11: e.EUROS_ENTERO,
                                        12: e.EUROS})
    if n:
        e.fila_total(ws, t, {
            **{c: f"=SUM({c}{primera}:{c}{ultima})" for c in "BCDEFHKLM"},
            "G": f"=IF(C{t}=0,0,F{t}/C{t})", "I": f"=IF(H{t}=0,0,F{t}/H{t})"},
            {"B": e.ENTERO, "C": e.DECIMAL, "D": e.DECIMAL, "E": e.ENTERO, "F": e.EUROS_ENTERO, "G": e.EUROS,
             "H": e.EUROS_ENTERO, "I": "0.00", "K": e.EUROS, "L": e.EUROS_ENTERO, "M": e.EUROS})
        ws[f"G{t + 1}"] = "media de la tienda"
        ws[f"G{t + 1}"].font = Font(italic=True, size=8, color=e.GRIS_TEXTO)
        # Podio: las 3 primeras filas del ranking en dorado; barras de datos en ventas por hora
        e.destacar_si(ws, f"A{primera}:A{ultima}", f"$J{primera}<=3", font=Font(bold=True))
        e.destacar_si(ws, f"J{primera}:J{ultima}", f"$J{primera}<=3")
        ws.conditional_formatting.add(f"G{primera}:G{ultima}",
                                      DataBarRule(start_type="num", start_value=0, end_type="max", color="5B9BD5"))
        ws.conditional_formatting.add(f"L{primera}:L{ultima}",
                                      CellIsRule(operator="greaterThan", formula=["0"], font=e.FUENTE_VERDE))
        grafico = e.barras(ws, 1, [7], 1, ultima, "Ventas por hora trabajada de cada vendedor",
                           horizontal=True, ancho=18, alto=max(6, 1.2 + 0.8 * n), formato_eje='#,##0 "€"',
                           etiquetas=True)
        ws.add_chart(grafico, f"A{t + 3}")
    e.nota(ws, f"A{t + 2}", "Comisión y bonus salen de los parámetros de la hoja Objetivos. "
                            "En dorado, el podio del ranking de ventas por hora.")
    ws.freeze_panes = "B2"
    e.anchos(ws, {"A": 30, "B": 10, "C": 9, "D": 9, "E": 9, "F": 12, "G": 11, "H": 12,
                  "I": 11, "J": 9, "K": 11, "L": 9, "M": 13})
    e.preparar_impresion(ws, f"Vendedores · {tienda}", "1:1")
    return n


def hoja_diaria(wb, tienda, d):
    ws = wb.create_sheet("Ventas diarias")
    ws.sheet_properties.tabColor = e.AZUL
    filas = []
    for i, (fecha, dia, pedidos, ventas) in enumerate(d["diario"]):
        r = i + 2
        filas.append([fecha, dia, pedidos, float(ventas),
                      f"=AVERAGE(D{max(2, r - 6)}:D{r})",                      # media móvil de 7 días
                      "=SUM($D$2:D{r})",                                       # acumulado del mes
                      "=ObjetivoVentas*DAY(A{r})/DAY(EOMONTH(A{r},0))",        # lo que "tocaría" llevar
                      "=F{r}-G{r}"])
    primera, ultima = e.escribir_tabla(
        ws, 1, ["Fecha", "Día", "Pedidos", "Ventas", "Media móvil 7 días", "Acumulado",
                "Objetivo acumulado", "Diferencia con el objetivo"],
        filas, "VentasDiarias", {0: e.FECHA, 3: e.EUROS_ENTERO, 4: e.EUROS_ENTERO, 5: e.EUROS_ENTERO,
                                 6: e.EUROS_ENTERO, 7: '+#,##0 "€";-#,##0 "€"'})
    t = ultima + 1
    e.fila_total(ws, t, {"C": f"=SUM(C{primera}:C{ultima})", "D": f"=SUM(D{primera}:D{ultima})"},
                 {"C": e.ENTERO, "D": e.EUROS_ENTERO})
    # Fines de semana sombreados y diferencia en verde o rojo
    e.destacar_si(ws, f"A{primera}:B{ultima}", f"WEEKDAY($A{primera},2)>5", fill=e.relleno(e.AZUL_CLARO))
    ws.conditional_formatting.add(f"H{primera}:H{ultima}",
                                  CellIsRule(operator="greaterThanOrEqual", formula=["0"], font=e.FUENTE_VERDE))
    ws.conditional_formatting.add(f"H{primera}:H{ultima}",
                                  CellIsRule(operator="lessThan", formula=["0"], font=e.FUENTE_ROJA))

    ws.add_chart(e.combinado(ws, 1, 4, 5, 1, ultima, "Ventas diarias y media móvil de 7 días",
                             ancho=17, alto=8, formato_barras='#,##0 "€"', formato_categorias="DD/MM"), "J2")
    ws.add_chart(e.lineas(ws, 1, [6, 7], 1, ultima, "Ritmo del mes: ventas acumuladas frente al objetivo",
                          ancho=17, alto=8, formato_eje='#,##0 "€"', formato_categorias="DD/MM",
                          colores=[e.AZUL, e.NARANJA]), "J19")
    e.nota(ws, f"A{t + 2}", "El objetivo acumulado reparte el objetivo del mes por igual entre sus días. "
                            "En azul claro, los fines de semana.")
    ws.freeze_panes = "A2"
    e.anchos(ws, {"A": 12, "B": 11, "C": 9, "D": 12, "E": 12, "F": 13, "G": 13, "H": 14})
    e.preparar_impresion(ws, f"Ventas diarias · {tienda}", "1:1")
    return ultima


def hoja_dia_semana(wb, tienda, ultima_diaria):
    ws = wb.create_sheet("Día de la semana")
    ws.sheet_properties.tabColor = e.AZUL
    rango = lambda col: f"'Ventas diarias'!${col}$2:${col}${ultima_diaria}"   # noqa: E731
    filas = [[dia,
              f"=COUNTIFS({rango('B')},A{{r}})",
              f"=SUMIFS({rango('D')},{rango('B')},A{{r}})",
              "=IF(B{r}=0,0,C{r}/B{r})",
              f"=IF(B{{r}}=0,0,SUMIFS({rango('C')},{rango('B')},A{{r}})/B{{r}})",
              "=IF(SUM($C$2:$C$8)=0,0,C{r}/SUM($C$2:$C$8))",
              "=IF(AVERAGE($D$2:$D$8)=0,0,D{r}/AVERAGE($D$2:$D$8))"]
             for dia in DIAS_SEMANA]
    primera, ultima = e.escribir_tabla(
        ws, 1, ["Día", "Días en el mes", "Ventas", "Venta media por día", "Pedidos medios por día",
                "% de las ventas", "Índice (100 % = día medio)"],
        filas, "DiaSemana", {2: e.EUROS_ENTERO, 3: e.EUROS_ENTERO, 4: e.DECIMAL, 5: e.PORCENTAJE,
                             6: "0%"})
    ws.conditional_formatting.add(f"G{primera}:G{ultima}", ColorScaleRule(
        start_type="min", start_color="F8696B", mid_type="num", mid_value=1, mid_color="FFFFFF",
        end_type="max", end_color="63BE7B"))
    ws.add_chart(e.barras(ws, 1, [4], 1, ultima, "Venta media según el día de la semana",
                          ancho=16, alto=7.5, formato_eje='#,##0 "€"', etiquetas=True), "I2")
    e.nota(ws, "A10", "Todo se calcula con SUMIFS y COUNTIFS sobre la hoja Ventas diarias.")
    e.anchos(ws, {"A": 12, "B": 10, "C": 12, "D": 13, "E": 13, "F": 11, "G": 13})
    e.preparar_impresion(ws, f"Día de la semana · {tienda}")


def hoja_productos(wb, tienda, d):
    ws = wb.create_sheet("Top productos")
    ws.sheet_properties.tabColor = e.AZUL
    ventas_tienda = ref_ind("ventas")
    filas = [[i, p, m, c, int(u), float(v),
              f"=IF({ventas_tienda}=0,0,F{{r}}/{ventas_tienda})",
              "=SUM($G$2:G{r})"]
             for i, (p, m, c, u, v) in enumerate(d["productos"], start=1)]
    primera, ultima = e.escribir_tabla(
        ws, 1, ["Nº", "Producto", "Marca", "Categoría", "Unidades", "Ventas",
                "% de las ventas de la tienda", "% acumulado"],
        filas, "TopProductos", {4: e.ENTERO, 5: e.EUROS_ENTERO, 6: e.PORCENTAJE, 7: e.PORCENTAJE})
    ws.conditional_formatting.add(f"F{primera}:F{ultima}",
                                  DataBarRule(start_type="num", start_value=0, end_type="max", color="5B9BD5"))
    if d["productos"]:
        ws.add_chart(e.combinado(ws, 1, 6, 8, 1, ultima, "Pareto: ventas del top 10 y % acumulado",
                                 eje_secundario=True, ancho=17, alto=8, formato_barras='#,##0 "€"',
                                 formato_linea="0%"), "A14")
    e.nota(ws, "A13", "Cuánto de lo que vende la tienda se concentra en sus 10 productos estrella.")
    e.anchos(ws, {"A": 5, "B": 44, "C": 13, "D": 18, "E": 10, "F": 12, "G": 15, "H": 12})
    e.preparar_impresion(ws, f"Top productos · {tienda}")


def hoja_comparativa(wb, tienda, cadena):
    ws = wb.create_sheet("Comparativa tiendas")
    ws.sheet_properties.tabColor = e.NARANJA
    # Ordenadas por ventas por hora (la métrica de productividad)
    cadena = sorted(cadena, key=lambda f: -(float(f[1]) / float(f[3]) if f[3] else 0))
    n = len(cadena)
    filas = [[nombre, float(v), int(p), "=IF(C{r}=0,0,B{r}/C{r})", float(h), "=IF(E{r}=0,0,B{r}/E{r})",
              float(c), "=IF(B{r}=0,0,G{r}/B{r})", f"=RANK(F{{r}},$F$2:$F${n + 1})"]
             for nombre, v, p, h, c in cadena]
    primera, ultima = e.escribir_tabla(
        ws, 1, ["Tienda", "Ventas", "Pedidos", "Ticket medio", "Horas trabajadas", "Ventas por hora",
                "Coste de personal", "Coste / ventas", "Ranking"],
        filas, "Comparativa", {1: e.EUROS_ENTERO, 2: e.ENTERO, 3: e.EUROS, 4: e.ENTERO, 5: e.EUROS,
                               6: e.EUROS_ENTERO, 7: e.PORCENTAJE})
    t = ultima + 1
    e.fila_total(ws, t, {**{c: f"=SUM({c}{primera}:{c}{ultima})" for c in "BCEG"},
                         "D": f"=IF(C{t}=0,0,B{t}/C{t})", "F": f"=IF(E{t}=0,0,B{t}/E{t})",
                         "H": f"=IF(B{t}=0,0,G{t}/B{t})"},
                 {"B": e.EUROS_ENTERO, "C": e.ENTERO, "D": e.EUROS, "E": e.ENTERO, "F": e.EUROS,
                  "G": e.EUROS_ENTERO, "H": e.PORCENTAJE}, texto="TOTAL CADENA")
    # La fila de ESTA tienda, resaltada; y su barra, en naranja
    e.destacar_si(ws, f"A{primera}:I{ultima}", f"$A{primera}={texto_excel(tienda)}", font=Font(bold=True))
    indice = [f[0] for f in cadena].index(tienda) if tienda in [f[0] for f in cadena] else None
    ws.add_chart(e.barras(ws, 1, [6], 1, ultima, "Ventas por hora trabajada en la cadena",
                          horizontal=True, ancho=17, alto=8, formato_eje='#,##0 "€"', destacar=indice,
                          etiquetas=True), "K2")
    e.nota(ws, f"A{t + 2}", "Ordenadas por ventas por hora trabajada. Resaltada, la tienda de este informe.")
    ws.freeze_panes = "B2"
    e.anchos(ws, {"A": 30, "B": 13, "C": 10, "D": 12, "E": 12, "F": 12, "G": 14, "H": 11, "I": 10})
    e.preparar_impresion(ws, f"Comparativa · {tienda}")
    return indice, ultima


def hoja_portada_tienda(wb, tienda, mes, num_categorias, ultima_diaria, num_vendedores,
                        indice_comparativa, ultima_comparativa):
    ws = wb.active
    ws.title = "Portada"
    ws.sheet_properties.tabColor = e.AZUL_OSCURO
    e.hoja_panel(ws, columnas=13, filas=60)
    e.banda_titulo(ws, "Informe mensual de tienda", f"{tienda}  ·  {nombre_mes(mes)}", 14)

    def var(clave):
        return f"={ref_ind(clave, 'D')}"
    e.tarjeta(ws, 6, 2, "Ventas", f"={ref_ind('ventas')}", e.EUROS_ENTERO, var("ventas"))
    e.tarjeta(ws, 6, 5, "Pedidos", f"={ref_ind('pedidos')}", e.ENTERO, var("pedidos"))
    e.tarjeta(ws, 6, 8, "Ticket medio", f"={ref_ind('ticket')}", e.EUROS, var("ticket"))
    e.tarjeta(ws, 6, 11, "Ventas por hora trabajada", f"={ref_ind('ventas_hora')}", e.EUROS, var("ventas_hora"))
    celda = e.tarjeta(ws, 11, 2, "Cumplimiento objetivo de ventas", f"={ref_ind('ventas', 'H')}", e.PORCENTAJE,
                      pie="=ObjetivoVentas", formato_pie='"Objetivo: "#,##0 "€"', color=e.NARANJA)
    ws.conditional_formatting.add(celda, CellIsRule(operator="greaterThanOrEqual", formula=["1"],
                                                    font=Font(bold=True, size=22, color=e.VERDE)))
    ws.conditional_formatting.add(celda, CellIsRule(operator="lessThan", formula=["1"],
                                                    font=Font(bold=True, size=22, color=e.ROJO)))
    e.tarjeta(ws, 11, 5, "Coste de personal / ventas", f"={ref_ind('coste_ventas')}", e.PORCENTAJE,
              var("coste_ventas"), bueno_si_sube=False, color=e.NARANJA)
    e.tarjeta(ws, 11, 8, "Absentismo", f"={ref_ind('absentismo')}", e.PORCENTAJE, var("absentismo"),
              bueno_si_sube=False, color=e.NARANJA)
    e.tarjeta(ws, 11, 11, "Tasa de devolución", f"={ref_ind('tasa_dev')}", e.PORCENTAJE, var("tasa_dev"),
              bueno_si_sube=False, color=e.NARANJA)

    # Gráficos (leen los datos de las otras hojas)
    diaria = wb["Ventas diarias"]
    ws.add_chart(e.combinado(diaria, 1, 4, 5, 1, ultima_diaria, "Ventas diarias y media móvil de 7 días",
                             ancho=13.2, alto=7.5, formato_barras='#,##0 "€"', formato_categorias="DD/MM"), "B16")
    if num_categorias:
        ws.add_chart(e.anillo(wb["Indicadores"], 10, 11, 6, 6 + num_categorias, "Ventas por categoría",
                              ancho=13.2, alto=7.5), "H16")
    ws.add_chart(e.barras(wb["Día de la semana"], 1, [4], 1, 8, "Venta media por día de la semana",
                          ancho=13.2, alto=7.5, formato_eje='#,##0 "€"'), "B31")
    comparativa = wb["Comparativa tiendas"]
    ws.add_chart(e.barras(comparativa, 1, [6], 1, ultima_comparativa,
                          "Ventas por hora: posición en la cadena", horizontal=True, ancho=13.2, alto=7.5,
                          formato_eje='#,##0 "€"', destacar=indice_comparativa), "H31")

    # Claves del mes: también con fórmulas (INDEX/MATCH buscan el nombre del máximo)
    e.titulo_seccion(ws, "B47", "Claves del mes", 12)
    ultima_vend = max(2, num_vendedores + 1)
    claves = [
        ("Mejor día del mes",
         f"=INDEX('Ventas diarias'!$A$2:$A${ultima_diaria},MATCH(MAX('Ventas diarias'!$D$2:$D${ultima_diaria}),"
         f"'Ventas diarias'!$D$2:$D${ultima_diaria},0))", e.FECHA,
         f"=MAX('Ventas diarias'!$D$2:$D${ultima_diaria})", e.EUROS_ENTERO),
        ("Día de la semana más fuerte",
         "=INDEX('Día de la semana'!$A$2:$A$8,MATCH(MAX('Día de la semana'!$D$2:$D$8),'Día de la semana'!$D$2:$D$8,0))",
         "@", "=MAX('Día de la semana'!$D$2:$D$8)", '#,##0 "€ de media"'),
        ("Vendedor más productivo (ventas por hora)",
         f"=IFERROR(INDEX(Vendedores!$A$2:$A${ultima_vend},MATCH(1,Vendedores!$J$2:$J${ultima_vend},0)),\"-\")",
         "@", f"=IFERROR(MAX(Vendedores!$G$2:$G${ultima_vend}),0)", '#,##0.00 "€/h"'),
        ("Categoría más vendida",
         f"=IFERROR(INDEX(Indicadores!$J$7:$J${6 + max(num_categorias, 1)},1),\"-\")", "@",
         f"=IFERROR(INDEX(Indicadores!$L$7:$L${6 + max(num_categorias, 1)},1),0)", '0.0%" de las ventas"'),
        ("Posición en la cadena (ventas por hora)",
         f"=IFERROR(INDEX('Comparativa tiendas'!$I:$I,MATCH({texto_excel(tienda)},'Comparativa tiendas'!$A:$A,0)),\"-\")",
         '0"º"', f"=COUNTA('Comparativa tiendas'!$A$2:$A${ultima_comparativa})", '"de "0" tiendas"'),
    ]
    for i, (etiqueta, valor, formato_valor, extra, formato_extra) in enumerate(claves):
        r = 48 + i
        ws.merge_cells(f"B{r}:F{r}")
        ws.merge_cells(f"G{r}:J{r}")
        ws.merge_cells(f"K{r}:M{r}")
        ws[f"B{r}"] = etiqueta
        ws[f"G{r}"] = valor
        ws[f"K{r}"] = extra
        ws[f"G{r}"].number_format = formato_valor
        ws[f"K{r}"].number_format = formato_extra
        ws[f"B{r}"].font = Font(color=e.GRIS_TEXTO)
        ws[f"G{r}"].font = Font(bold=True, color=e.AZUL_OSCURO)
        ws[f"K{r}"].font = Font(bold=True, color=e.NARANJA)
        for c in range(2, 14):
            ws.cell(r, c).fill = e.relleno("FFFFFF")
            ws.cell(r, c).border = e.Border(bottom=e.LINEA_FINA)
    e.preparar_impresion(ws, f"Portada · {tienda}", una_pagina=True)
    ws.print_area = "A1:N53"


def informe_tienda(conn, id_tienda, tienda, mes, carpeta, cadena):
    d = datos_tienda(conn, id_tienda, mes)
    wb = Workbook()
    e.propiedades(wb, f"Informe mensual {tienda} {mes:%Y-%m}", "Informe de tienda")
    # Primero las hojas de datos (la portada necesita saber dónde están)
    num_categorias = hoja_indicadores(wb, tienda, mes, d)
    hoja_objetivos(wb, tienda, mes, d)
    num_vendedores = hoja_vendedores(wb, tienda, d)
    ultima_diaria = hoja_diaria(wb, tienda, d)
    hoja_dia_semana(wb, tienda, ultima_diaria)
    hoja_productos(wb, tienda, d)
    indice, ultima_comparativa = hoja_comparativa(wb, tienda, cadena)
    hoja_portada_tienda(wb, tienda, mes, num_categorias, ultima_diaria, num_vendedores,
                        indice, ultima_comparativa)
    wb.active = 0
    ruta = carpeta / f"informe_tienda_{codigo(tienda)}_{mes:%Y-%m}.xlsx"
    wb.save(ruta)
    return ruta


# =====================================================================
#  INFORME DE RRHH
# =====================================================================

COLUMNAS_DATOS = [   # (título, nombre definido, formato)
    ("Mes", "DatosMes", "@"), ("Centro", "DatosCentro", "@"), ("Tipo", "DatosTipo", "@"),
    ("Plantilla", "DatosPlantilla", e.ENTERO), ("Días del mes", "DatosDias", e.ENTERO),
    ("Plantilla x días", "DatosPlantillaDias", e.ENTERO), ("Horas", "DatosHoras", e.ENTERO),
    ("Horas extra", "DatosHorasExtra", e.DECIMAL), ("Días de baja", "DatosBaja", e.ENTERO),
    ("Días de vacaciones", "DatosVacaciones", e.ENTERO), ("Días de permiso", "DatosPermiso", e.ENTERO),
    ("Coste de personal", "DatosCoste", e.EUROS_ENTERO), ("Ventas", "DatosVentas", e.EUROS_ENTERO),
]


def suma(nombre, *condiciones):
    """SUMIFS sobre la hoja Datos: suma('DatosHoras', ('DatosMes', 'MesInforme'))."""
    return f"SUMIFS({nombre}," + ",".join(f"{a},{b}" for a, b in condiciones) + ")"


def hoja_datos_rrhh(wb, conn, mes):
    ws = wb.create_sheet("Datos")
    ws.sheet_properties.tabColor = e.GRIS_TEXTO
    filas = conn.execute("""
        SELECT to_char(mes, 'YYYY-MM'), centro, tipo, plantilla,
               EXTRACT(DAY FROM (mes + INTERVAL '1 month' - INTERVAL '1 day'))::int,
               horas, horas_extra, dias_baja, dias_vacaciones, dias_permiso, coste_personal, ventas
        FROM marts.rpt_rrhh_centro_mes
        WHERE mes > %s - INTERVAL '12 months' AND mes <= %s
        ORDER BY mes, tipo DESC, centro
    """, (mes, mes)).fetchall()
    datos = [[m, c, t, int(p), dias, "=D{r}*E{r}", float(h), float(hx), int(b), int(v), int(pe),
              float(co), float(ve or 0)]
             for m, c, t, p, dias, h, hx, b, v, pe, co, ve in filas]
    primera, ultima = e.escribir_tabla(ws, 1, [c[0] for c in COLUMNAS_DATOS], datos, "Datos",
                                       {i: c[2] for i, c in enumerate(COLUMNAS_DATOS)}, estilo="TableStyleLight9")
    for i, (_t, nombre, _f) in enumerate(COLUMNAS_DATOS):
        letra = e.get_column_letter(i + 1)
        e.nombre_definido(wb, nombre, "Datos", f"{letra}{primera}:{letra}{ultima}")
    e.anchos(ws, {"A": 9, "B": 28, "C": 9, **{e.get_column_letter(i): 12 for i in range(4, 14)}})
    ws.freeze_panes = "A2"
    meses = sorted({f[0] for f in filas})
    return meses


def hoja_parametros_rrhh(wb, mes):
    ws = wb.create_sheet("Parámetros")
    ws.sheet_properties.tabColor = "FFC000"
    ws.sheet_view.showGridLines = False
    e.banda_titulo(ws, "Parámetros del informe", nombre_mes(mes), 4)
    ws["A5"] = "Las celdas amarillas se pueden cambiar: alertas y conciliaciones se recalculan solas."
    ws["A5"].font = Font(bold=True, color=e.AZUL)
    parametros = [
        ("Mes del informe", "MesInforme", f"{mes:%Y-%m}", "@", False),
        ("Mes anterior", "MesAnterior", f"{mes_anterior(mes):%Y-%m}", "@", False),
        ("Primer día del mes", "InicioMes", mes, e.FECHA, False),
        ("Último día del mes", "FinMes", fin_de_mes(mes), e.FECHA, False),
        ("Umbral de absentismo (alerta en rojo por encima)", "UmbralAbsentismo", 0.03, e.PORCENTAJE, True),
        ("Precio pactado de la hora extra", "PrecioHoraExtra", 15, e.EUROS, True),
        ("Tolerancia al conciliar con la nómina", "ToleranciaNomina", 1, e.EUROS, True),
    ]
    for i, (texto, nombre, valor, formato, editable) in enumerate(parametros):
        r = 7 + i
        ws[f"A{r}"] = texto
        ws[f"A{r}"].border = e.Border(bottom=e.LINEA_FINA)
        if editable:
            e.celda_editable(ws, f"B{r}", valor, formato)
        else:
            ws[f"B{r}"] = valor
            ws[f"B{r}"].number_format = formato
            ws[f"B{r}"].font = Font(bold=True, color=e.GRIS_TEXTO)
        ws[f"B{r}"].alignment = Alignment(horizontal="right")
        e.nombre_definido(wb, nombre, "Parámetros", f"B{r}")
    e.anchos(ws, {"A": 50, "B": 16})
    e.proteger(ws)


def hoja_centros(wb, conn, mes):
    ws = wb.create_sheet("Centros")
    ws.sheet_properties.tabColor = e.AZUL
    centros = conn.execute("""
        SELECT centro, tipo, plantilla, horas, horas_extra, dias_baja, dias_vacaciones, dias_permiso,
               coste_personal, ventas
        FROM marts.rpt_rrhh_centro_mes WHERE mes = %s ORDER BY tipo DESC, centro
    """, (mes,)).fetchall()
    filas = [[c, t.capitalize().replace("Almacen", "Almacén"), int(p), float(h), float(hx), "=IF(C{r}=0,0,E{r}/C{r})",
              int(b), int(v), int(pe), "=IF(C{r}=0,0,G{r}/(C{r}*DAY(FinMes)))", float(co),
              "=IF(C{r}=0,0,K{r}/C{r})", float(ve) if t == "tienda" else None,
              '=IF(N(M{r})=0,"",K{r}/M{r})']
             for c, t, p, h, hx, b, v, pe, co, ve in centros]
    primera, ultima = e.escribir_tabla(
        ws, 1, ["Centro", "Tipo", "Plantilla", "Horas", "Horas extra", "Horas extra por empleado",
                "Días de baja", "Días de vacaciones", "Días de permiso", "Absentismo", "Coste de personal",
                "Coste por empleado", "Ventas en tienda", "Coste / ventas"],
        filas, "Centros", {3: e.ENTERO, 4: e.DECIMAL, 5: e.DECIMAL, 9: e.PORCENTAJE, 10: e.EUROS_ENTERO,
                           11: e.EUROS_ENTERO, 12: e.EUROS_ENTERO, 13: e.PORCENTAJE})
    t = ultima + 1
    e.fila_total(ws, t, {
        **{c: f"=SUM({c}{primera}:{c}{ultima})" for c in "CDEGHIKM"},
        "F": f"=IF(C{t}=0,0,E{t}/C{t})", "J": f"=IF(C{t}=0,0,G{t}/(C{t}*DAY(FinMes)))",
        "L": f"=IF(C{t}=0,0,K{t}/C{t})", "N": f'=IF(M{t}=0,"",SUMIFS(K{primera}:K{ultima},B{primera}:B{ultima},"Tienda")/M{t})'},
        {"C": e.ENTERO, "D": e.ENTERO, "E": e.DECIMAL, "F": e.DECIMAL, "J": e.PORCENTAJE, "K": e.EUROS_ENTERO,
         "L": e.EUROS_ENTERO, "M": e.EUROS_ENTERO, "N": e.PORCENTAJE})
    # Alerta: absentismo por encima del umbral (editable en Parámetros)
    e.destacar_si(ws, f"J{primera}:J{ultima}", f"$J{primera}>UmbralAbsentismo", fill=e.RELLENO_ROJO,
                  font=Font(bold=True, color=e.ROJO))
    e.destacar_si(ws, f"A{primera}:A{ultima}", f"$J{primera}>UmbralAbsentismo", fill=e.RELLENO_ROJO)
    ws.conditional_formatting.add(f"F{primera}:F{ultima}", ColorScaleRule(
        start_type="min", start_color="FFFFFF", end_type="max", end_color="F4B183"))
    ws.conditional_formatting.add(f"L{primera}:L{ultima}",
                                  DataBarRule(start_type="num", start_value=0, end_type="max", color="8FAADC"))
    ws.add_chart(e.barras(ws, 1, [10], 1, ultima, "Absentismo por centro", horizontal=True, ancho=16,
                          alto=8, formato_eje="0.0%", etiquetas=True), f"A{t + 3}")
    ws.add_chart(e.barras(ws, 1, [6], 1, ultima, "Horas extra por empleado", horizontal=True, ancho=16,
                          alto=8, formato_eje="0.0", colores=[e.NARANJA], etiquetas=True), f"F{t + 3}")
    e.nota(ws, f"A{t + 1 + 1}", "En rojo, los centros que superan el umbral de absentismo de la hoja Parámetros.")
    ws.freeze_panes = "B2"
    e.anchos(ws, {"A": 28, "B": 9, "C": 10, "D": 9, "E": 9, "F": 11, "G": 9, "H": 11, "I": 9,
                  "J": 11, "K": 12, "L": 11, "M": 12, "N": 10})
    e.preparar_impresion(ws, "Centros · Recursos Humanos", "1:1")
    e.nombre_definido(wb, "ListaCentros", "Centros", f"A{primera}:A{ultima}")
    return [c[0] for c in centros], primera, ultima


def hoja_ficha_centro(wb, centros, meses, mes):
    """La hoja interactiva: un desplegable elige el centro y todo se recalcula con SUMIFS."""
    ws = wb.create_sheet("Ficha de centro")
    ws.sheet_properties.tabColor = e.NARANJA
    e.hoja_panel(ws, columnas=13, filas=58)
    e.banda_titulo(ws, "Ficha de centro", f"Elige un centro en el desplegable  ·  {nombre_mes(mes)}", 14)

    ws.merge_cells("B6:D6")
    ws.merge_cells("E6:I6")
    ws["B6"] = "CENTRO:"
    ws["B6"].font = Font(bold=True, size=12, color=e.AZUL_OSCURO)
    ws["B6"].alignment = Alignment(horizontal="right", vertical="center")
    selector = ws["E6"]
    selector.value = next((c for c in centros if c.startswith("TechNova")), centros[0])
    selector.font = Font(bold=True, size=14, color="0000FF")
    selector.fill = e.RELLENO_EDITABLE
    selector.alignment = Alignment(horizontal="center", vertical="center")
    for c in range(5, 10):
        ws.cell(6, c).fill = e.RELLENO_EDITABLE
        ws.cell(6, c).border = e.CAJA
    ws.row_dimensions[6].height = 28
    lista = DataValidation(type="list", formula1="=ListaCentros", allow_blank=False, showErrorMessage=True,
                           errorTitle="Centro no válido", error="Elige un centro de la lista",
                           promptTitle="Elige un centro", prompt="Despliega la lista: toda la hoja se recalcula")
    lista.showInputMessage = True
    ws.add_data_validation(lista)
    lista.add("E6")
    e.nombre_definido(wb, "CentroElegido", "Ficha de centro", "E6")
    ws["J6"] = "◄ despliega la lista"
    ws["J6"].font = Font(italic=True, color=e.GRIS_TEXTO)
    ws["J6"].alignment = Alignment(vertical="center")

    def del_centro(nombre, mes_nombre):
        return suma(nombre, ("DatosCentro", "CentroElegido"), ("DatosMes", mes_nombre))

    def variacion(nombre):
        return f'=IFERROR({del_centro(nombre, "MesInforme")}/{del_centro(nombre, "MesAnterior")}-1,"")'

    absentismo = (f'=IFERROR({del_centro("DatosBaja", "MesInforme")}/'
                  f'{del_centro("DatosPlantillaDias", "MesInforme")},0)')
    absentismo_ant = (f'IFERROR({del_centro("DatosBaja", "MesAnterior")}/'
                      f'{del_centro("DatosPlantillaDias", "MesAnterior")},0)')
    e.tarjeta(ws, 8, 2, "Plantilla", f"={del_centro('DatosPlantilla', 'MesInforme')}", e.ENTERO,
              variacion("DatosPlantilla"))
    e.tarjeta(ws, 8, 5, "Horas extra", f"={del_centro('DatosHorasExtra', 'MesInforme')}", e.DECIMAL,
              variacion("DatosHorasExtra"), bueno_si_sube=False)
    celda_abs = e.tarjeta(ws, 8, 8, "Absentismo", absentismo, e.PORCENTAJE,
                          f'=IFERROR({absentismo[1:]}/{absentismo_ant}-1,"")', bueno_si_sube=False)
    e.tarjeta(ws, 8, 11, "Coste de personal", f"={del_centro('DatosCoste', 'MesInforme')}", e.EUROS_ENTERO,
              variacion("DatosCoste"), bueno_si_sube=False)
    e.tarjeta(ws, 13, 2, "Ventas del centro", f"={del_centro('DatosVentas', 'MesInforme')}", e.EUROS_ENTERO,
              variacion("DatosVentas"), color=e.NARANJA)
    e.tarjeta(ws, 13, 5, "Coste de personal / ventas",
              f'=IFERROR({del_centro("DatosCoste", "MesInforme")}/{del_centro("DatosVentas", "MesInforme")},"-")',
              e.PORCENTAJE, pie='=IF(INDEX(DatosTipo,MATCH(CentroElegido,DatosCentro,0))="tienda","tienda","almacén: sin ventas")',
              color=e.NARANJA)
    e.tarjeta(ws, 13, 8, "Ranking de absentismo",
              f"=COUNTIF(Centros!$J$2:$J${len(centros) + 1},\">\"&{celda_abs})+1", '0"º"',
              pie="=COUNTA(ListaCentros)", formato_pie='"de "0" centros (1º = el más alto)"', color=e.NARANJA)
    e.tarjeta(ws, 13, 11, "Horas extra por empleado",
              f'=IFERROR({del_centro("DatosHorasExtra", "MesInforme")}/{del_centro("DatosPlantilla", "MesInforme")},0)',
              e.DECIMAL, pie="=UmbralAbsentismo", formato_pie='"umbral de absentismo: "0.0%', color=e.NARANJA)
    ws.conditional_formatting.add(celda_abs, FormulaRule(formula=[f"{celda_abs}>UmbralAbsentismo"],
                                                         font=Font(bold=True, size=22, color=e.ROJO)))

    # Evolución del centro elegido (12 meses): tabla con fórmulas que alimenta los gráficos
    e.titulo_seccion(ws, "B35", "Evolución del centro elegido en los últimos 12 meses", 12)
    cabecera = ["Mes", "Horas extra", "Absentismo", "Coste de personal", "Ventas", "Plantilla"]
    for c, titulo in enumerate(cabecera):
        celda = ws.cell(36, 2 + c * 2, titulo)
        ws.merge_cells(start_row=36, start_column=2 + c * 2, end_row=36, end_column=3 + c * 2)
        celda.font = Font(bold=True, color="FFFFFF")
        celda.alignment = Alignment(horizontal="center")
        for k in (0, 1):
            ws.cell(36, 2 + c * 2 + k).fill = e.relleno(e.AZUL_OSCURO)
    # Para los gráficos hacen falta columnas simples: los datos van en N:S (a la derecha, fuera del panel)
    ws["O36"], ws["P36"], ws["Q36"], ws["R36"] = "Horas extra", "Absentismo", "Coste de personal", "Mes"
    for i, m in enumerate(meses):
        r = 37 + i
        ws[f"R{r}"] = m
        ws[f"O{r}"] = f'={suma("DatosHorasExtra", ("DatosCentro", "CentroElegido"), ("DatosMes", f"R{r}"))}'
        ws[f"P{r}"] = (f'=IFERROR({suma("DatosBaja", ("DatosCentro", "CentroElegido"), ("DatosMes", f"R{r}"))}/'
                       f'{suma("DatosPlantillaDias", ("DatosCentro", "CentroElegido"), ("DatosMes", f"R{r}"))},0)')
        ws[f"Q{r}"] = f'={suma("DatosCoste", ("DatosCentro", "CentroElegido"), ("DatosMes", f"R{r}"))}'
        valores = [f"=R{r}", f"=O{r}", f"=P{r}", f"=Q{r}",
                   f'={suma("DatosVentas", ("DatosCentro", "CentroElegido"), ("DatosMes", f"R{r}"))}',
                   f'={suma("DatosPlantilla", ("DatosCentro", "CentroElegido"), ("DatosMes", f"R{r}"))}']
        formatos = ["@", e.DECIMAL, e.PORCENTAJE, e.EUROS_ENTERO, e.EUROS_ENTERO, e.ENTERO]
        for c, (valor, formato) in enumerate(zip(valores, formatos)):
            col = 2 + c * 2
            ws.merge_cells(start_row=r, start_column=col, end_row=r, end_column=col + 1)
            celda = ws.cell(r, col, valor)
            celda.number_format = formato
            celda.alignment = Alignment(horizontal="center")
            for k in (0, 1):
                ws.cell(r, col + k).fill = e.relleno("FFFFFF" if i % 2 else e.AZUL_CLARO)
    ultima = 36 + len(meses)
    for col in "OPQR":
        ws.column_dimensions[col].hidden = True
    ws.add_chart(e.combinado(ws, 18, 17, 15, 36, ultima, "Coste de personal (barras) y horas extra (línea)",
                             eje_secundario=True, ancho=13.2, alto=7.5, formato_barras='#,##0 "€"',
                             formato_linea="#,##0"), "B18")
    ws.add_chart(e.lineas(ws, 18, [16], 36, ultima, "Absentismo mes a mes", ancho=13.2, alto=7.5,
                          formato_eje="0.0%", colores=[e.ROJO]), "H18")
    e.preparar_impresion(ws, "Ficha de centro · Recursos Humanos", una_pagina=True)
    ws.print_area = f"A1:N{ultima + 1}"


def hoja_horas_extra(wb, conn, mes):
    ws = wb.create_sheet("Horas extra")
    ws.sheet_properties.tabColor = e.AZUL
    filas = conn.execute("""
        SELECT e.empleado, e.puesto, e.ubicacion, ROUND(SUM(j.horas_extra), 2),
               COALESCE(MAX(n.importe_horas_extra), 0)
        FROM marts.fct_jornadas j
        JOIN marts.dim_empleado e USING (id_empleado)
        LEFT JOIN marts.fct_nominas n ON n.id_empleado = j.id_empleado AND n.mes = %s
        WHERE j.fecha BETWEEN %s AND %s
        GROUP BY e.empleado, e.puesto, e.ubicacion
        HAVING SUM(j.horas_extra) > 0
        ORDER BY 4 DESC
    """, (mes, mes, fin_de_mes(mes))).fetchall()
    datos = [[a, b, c, float(h), float(i), "=D{r}*PrecioHoraExtra", "=E{r}-F{r}",
              '=IF(ABS(G{r})<=ToleranciaNomina,"Cuadra",IF(G{r}<0,"Pagado de menos","Pagado de más"))']
             for a, b, c, h, i in filas]
    primera, ultima = e.escribir_tabla(
        ws, 1, ["Empleado", "Puesto", "Centro", "Horas extra fichadas", "Pagado en nómina",
                "Importe esperado", "Diferencia", "Estado"],
        datos, "HorasExtra", {3: e.DECIMAL, 4: e.EUROS, 5: e.EUROS, 6: '+#,##0.00 "€";-#,##0.00 "€";0.00 "€"'})
    t = ultima + 1
    e.fila_total(ws, t, {c: f"=SUM({c}{primera}:{c}{ultima})" for c in "DEFG"},
                 {"D": e.DECIMAL, "E": e.EUROS, "F": e.EUROS, "G": '+#,##0.00 "€";-#,##0.00 "€";0.00 "€"'})
    ws[f"H{t}"] = f'=COUNTIF(H{primera}:H{ultima},"<>Cuadra")&" a revisar"'
    ws[f"H{t}"].font = Font(bold=True, color=e.ROJO)
    e.destacar_si(ws, f"H{primera}:H{ultima}", f'$H{primera}<>"Cuadra"', fill=e.RELLENO_ROJO,
                  font=Font(bold=True, color=e.ROJO))
    e.destacar_si(ws, f"H{primera}:H{ultima}", f'$H{primera}="Cuadra"', fill=e.RELLENO_VERDE,
                  font=Font(color=e.VERDE))
    ws.conditional_formatting.add(f"D{primera}:D{ultima}",
                                  DataBarRule(start_type="num", start_value=0, end_type="max", color="F4B183"))
    e.nota(ws, f"A{t + 2}", "Conciliación: horas extra fichadas x precio pactado frente a lo pagado en la nómina. "
                            "Precio y tolerancia se cambian en la hoja Parámetros.")
    ws.freeze_panes = "B2"
    e.anchos(ws, {"A": 30, "B": 22, "C": 28, "D": 12, "E": 13, "F": 13, "G": 12, "H": 17})
    e.preparar_impresion(ws, "Horas extra · Recursos Humanos", "1:1")
    return ultima


def hoja_ausencias(wb, conn, mes, centros):
    ws = wb.create_sheet("Ausencias")
    ws.sheet_properties.tabColor = e.AZUL
    filas = conn.execute("""
        SELECT e.empleado, e.ubicacion, a.tipo, a.desde, a.hasta
        FROM stg.stg_rrhh_ausencias a JOIN marts.dim_empleado e USING (id_empleado)
        WHERE a.desde <= %s AND a.hasta >= %s
        ORDER BY e.ubicacion, a.desde
    """, (fin_de_mes(mes), mes)).fetchall()
    datos = [[a, b, TIPOS_AUSENCIA.get(c, c), d, h, "=E{r}-D{r}+1",
              "=MAX(0,MIN(E{r},FinMes)-MAX(D{r},InicioMes)+1)"] for a, b, c, d, h in filas]
    primera, ultima = e.escribir_tabla(
        ws, 1, ["Empleado", "Centro", "Tipo", "Desde", "Hasta", "Días naturales", "Días dentro del mes"],
        datos, "Ausencias", {3: e.FECHA, 4: e.FECHA, 5: e.ENTERO, 6: e.ENTERO})

    # Matriz centro x tipo (como una tabla dinámica, pero con SUMIFS: se actualiza sola)
    e.titulo_seccion(ws, "J1", "Días de ausencia en el mes por centro y tipo", 5)
    tipos = list(TIPOS_AUSENCIA.values())
    for c, titulo in enumerate(["Centro"] + tipos + ["Total"]):
        celda = ws.cell(3, 10 + c, titulo)
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = e.relleno(e.AZUL_OSCURO)
        celda.alignment = Alignment(horizontal="center", wrap_text=True)
    for i, centro in enumerate(centros):
        r = 4 + i
        ws.cell(r, 10, centro)
        for c, tipo in enumerate(tipos):
            ws.cell(r, 11 + c, f'=SUMIFS($G${primera}:$G${ultima},$B${primera}:$B${ultima},$J{r},'
                               f'$C${primera}:$C${ultima},{e.get_column_letter(11 + c)}$3)')
        ws.cell(r, 14, f"=SUM(K{r}:M{r})").font = Font(bold=True)
    fin_matriz = 3 + len(centros)
    t = fin_matriz + 1
    e.fila_total(ws, t, {c: f"=SUM({c}4:{c}{fin_matriz})" for c in "KLMN"}, {}, columna_titulo=10)
    ws.conditional_formatting.add(f"K4:M{fin_matriz}", ColorScaleRule(
        start_type="num", start_value=0, start_color="FFFFFF", end_type="max", end_color="5B9BD5"))
    # Resumen por tipo en vertical (para el gráfico de anillo)
    ws.cell(t + 2, 10, "Tipo").font = Font(bold=True)
    ws.cell(t + 2, 11, "Días").font = Font(bold=True)
    for i, tipo in enumerate(tipos):
        ws.cell(t + 3 + i, 10, tipo)
        ws.cell(t + 3 + i, 11, f"={e.get_column_letter(11 + i)}{t}")
    ws.add_chart(e.anillo(ws, 10, 11, t + 2, t + 2 + len(tipos), "Días de ausencia por tipo",
                          ancho=13, alto=7), f"J{t + 7}")
    ws.freeze_panes = "A2"
    e.anchos(ws, {"A": 28, "B": 28, "C": 15, "D": 11, "E": 11, "F": 10, "G": 11, "H": 3, "I": 3,
                  "J": 28, "K": 12, "L": 12, "M": 12, "N": 10})
    e.preparar_impresion(ws, "Ausencias · Recursos Humanos", "1:1")
    return t + 2, len(tipos)


def hoja_evolucion(wb, meses):
    ws = wb.create_sheet("Evolución")
    ws.sheet_properties.tabColor = e.AZUL
    filas = [[m,
              f'={suma("DatosPlantilla", ("DatosMes", "A{r}"))}',
              f'={suma("DatosHoras", ("DatosMes", "A{r}"))}',
              f'={suma("DatosHorasExtra", ("DatosMes", "A{r}"))}',
              f'={suma("DatosBaja", ("DatosMes", "A{r}"))}',
              f'=IFERROR(E{{r}}/{suma("DatosPlantillaDias", ("DatosMes", "A{r}"))},0)',
              f'={suma("DatosCoste", ("DatosMes", "A{r}"))}',
              f'={suma("DatosVentas", ("DatosMes", "A{r}"), ("DatosTipo", texto_excel("tienda")))}',
              f'=IFERROR({suma("DatosCoste", ("DatosMes", "A{r}"), ("DatosTipo", texto_excel("tienda")))}/H{{r}},"")']
             for m in meses]
    primera, ultima = e.escribir_tabla(
        ws, 1, ["Mes", "Plantilla", "Horas", "Horas extra", "Días de baja", "Absentismo", "Coste de personal",
                "Ventas en tiendas", "Coste / ventas en tiendas"],
        filas, "Evolucion", {1: e.ENTERO, 2: e.ENTERO, 3: e.DECIMAL, 4: e.ENTERO, 5: e.PORCENTAJE,
                             6: e.EUROS_ENTERO, 7: e.EUROS_ENTERO, 8: e.PORCENTAJE})
    ws.conditional_formatting.add(f"F{primera}:F{ultima}", FormulaRule(
        formula=[f"$F{primera}>UmbralAbsentismo"], font=Font(bold=True, color=e.ROJO)))
    ws.conditional_formatting.add(f"G{primera}:G{ultima}",
                                  DataBarRule(start_type="num", start_value=0, end_type="max", color="8FAADC"))
    ws.add_chart(e.combinado(ws, 1, 7, 4, 1, ultima, "Coste de personal (barras) y horas extra (línea)",
                             eje_secundario=True, ancho=17, alto=8, formato_barras='#,##0 "€"',
                             formato_linea="#,##0"), "K2")
    ws.add_chart(e.lineas(ws, 1, [6], 1, ultima, "Absentismo de la empresa", ancho=17, alto=8,
                          formato_eje="0.0%", colores=[e.ROJO]), "K19")
    e.nota(ws, f"A{ultima + 2}", "Todo se calcula con SUMIFS sobre la hoja Datos.")
    ws.freeze_panes = "B2"
    e.anchos(ws, {"A": 10, "B": 10, "C": 10, "D": 11, "E": 10, "F": 11, "G": 14, "H": 14, "I": 13})
    e.preparar_impresion(ws, "Evolución · Recursos Humanos", "1:1")
    return ultima


def hoja_portada_rrhh(wb, mes, fila_tipos, num_tipos, ultima_evolucion, ultima_centros, ultima_horas_extra):
    ws = wb.active
    ws.title = "Portada"
    ws.sheet_properties.tabColor = e.AZUL_OSCURO
    e.hoja_panel(ws, columnas=13, filas=48)
    e.banda_titulo(ws, "Informe mensual de Recursos Humanos", f"Toda la empresa  ·  {nombre_mes(mes)}", 14)

    def del_mes(nombre, mes_nombre="MesInforme", *extra):
        return suma(nombre, ("DatosMes", mes_nombre), *extra)

    def variacion(nombre, *extra):
        return f'=IFERROR({del_mes(nombre, "MesInforme", *extra)}/{del_mes(nombre, "MesAnterior", *extra)}-1,"")'

    def ratio(a, b, mes_nombre, *extra):
        return f"IFERROR({del_mes(a, mes_nombre, *extra)}/{del_mes(b, mes_nombre, *extra)},0)"

    tienda = ("DatosTipo", texto_excel("tienda"))
    e.tarjeta(ws, 6, 2, "Plantilla", f"={del_mes('DatosPlantilla')}", e.ENTERO, variacion("DatosPlantilla"))
    e.tarjeta(ws, 6, 5, "Horas trabajadas", f"={del_mes('DatosHoras')}", e.ENTERO, variacion("DatosHoras"))
    e.tarjeta(ws, 6, 8, "Horas extra", f"={del_mes('DatosHorasExtra')}", e.ENTERO, variacion("DatosHorasExtra"),
              bueno_si_sube=False)
    e.tarjeta(ws, 6, 11, "Absentismo", f"={ratio('DatosBaja', 'DatosPlantillaDias', 'MesInforme')}", e.PORCENTAJE,
              f'=IFERROR({ratio("DatosBaja", "DatosPlantillaDias", "MesInforme")}/'
              f'{ratio("DatosBaja", "DatosPlantillaDias", "MesAnterior")}-1,"")', bueno_si_sube=False)
    e.tarjeta(ws, 11, 2, "Coste de personal", f"={del_mes('DatosCoste')}", e.EUROS_ENTERO, variacion("DatosCoste"),
              bueno_si_sube=False, color=e.NARANJA)
    e.tarjeta(ws, 11, 5, "Coste / ventas en tiendas",
              f"={ratio('DatosCoste', 'DatosVentas', 'MesInforme', tienda)}", e.PORCENTAJE,
              f'=IFERROR({ratio("DatosCoste", "DatosVentas", "MesInforme", tienda)}/'
              f'{ratio("DatosCoste", "DatosVentas", "MesAnterior", tienda)}-1,"")', bueno_si_sube=False,
              color=e.NARANJA)
    e.tarjeta(ws, 11, 8, "Horas extra a revisar en nómina",
              f"=COUNTIF('Horas extra'!$H$2:$H${ultima_horas_extra},\"<>Cuadra\")",
              e.ENTERO, pie=f"=COUNTA('Horas extra'!$A$2:$A${ultima_horas_extra})", formato_pie='"de "0" empleados con horas extra"',
              color=e.NARANJA)
    e.tarjeta(ws, 11, 11, "Centros con alerta de absentismo",
              f"=COUNTIF(Centros!$J$2:$J${ultima_centros},\">\"&UmbralAbsentismo)", e.ENTERO, pie="=UmbralAbsentismo",
              formato_pie='"por encima del "0.0%', color=e.NARANJA)

    evolucion = wb["Evolución"]
    ws.add_chart(e.combinado(evolucion, 1, 7, 4, 1, ultima_evolucion,
                             "Coste de personal (barras) y horas extra (línea)", eje_secundario=True,
                             ancho=13.2, alto=7.5, formato_barras='#,##0 "€"', formato_linea="#,##0"), "B16")
    ws.add_chart(e.anillo(wb["Ausencias"], 10, 11, fila_tipos, fila_tipos + num_tipos,
                          "Días de ausencia por tipo", ancho=13.2, alto=7.5), "H16")
    ws.add_chart(e.barras(wb["Centros"], 1, [10], 1, ultima_centros, "Absentismo por centro", horizontal=True,
                          ancho=13.2, alto=7.5, formato_eje="0.0%"), "B31")
    ws.add_chart(e.lineas(evolucion, 1, [6], 1, ultima_evolucion, "Absentismo en los últimos 12 meses",
                          ancho=13.2, alto=7.5, formato_eje="0.0%", colores=[e.ROJO]), "H31")
    e.nota(ws, "B46", "Consejo: en la hoja 'Ficha de centro' puedes elegir un centro en el desplegable "
                      "y ver todos sus datos y su evolución.")
    e.preparar_impresion(ws, "Portada · Recursos Humanos", una_pagina=True)
    ws.print_area = "A1:N46"


def informe_rrhh(conn, mes, carpeta):
    wb = Workbook()
    e.propiedades(wb, f"Informe mensual de RRHH {mes:%Y-%m}", "Informe de Recursos Humanos")
    centros, _primera, ultima_centros = hoja_centros(wb, conn, mes)
    ultima_horas_extra = hoja_horas_extra(wb, conn, mes)
    fila_tipos, num_tipos = hoja_ausencias(wb, conn, mes, centros)
    meses = sorted(f"{mes_anterior(mes, n):%Y-%m}" for n in range(12))
    ultima_evolucion = hoja_evolucion(wb, meses)
    hoja_ficha_centro(wb, centros, meses, mes)
    hoja_parametros_rrhh(wb, mes)
    hoja_datos_rrhh(wb, conn, mes)
    hoja_portada_rrhh(wb, mes, fila_tipos, num_tipos, ultima_evolucion, ultima_centros, ultima_horas_extra)
    # Orden de las pestañas: portada, ficha interactiva, detalle, y al final parámetros y datos
    orden = ["Portada", "Centros", "Ficha de centro", "Horas extra", "Ausencias", "Evolución", "Parámetros", "Datos"]
    wb._sheets = [wb[nombre] for nombre in orden]
    wb.active = 0
    ruta = carpeta / f"informe_rrhh_{mes:%Y-%m}.xlsx"
    wb.save(ruta)
    return ruta


# =====================================================================
#  PROCESO
# =====================================================================

def generar(mes: date):
    """Genera todos los informes de un mes. Devuelve la lista de ficheros creados."""
    mes = mes.replace(day=1)
    carpeta = CARPETA_INFORMES / mes.strftime("%Y-%m")
    carpeta.mkdir(parents=True, exist_ok=True)
    with conectar_dw() as conn:
        if not conn.execute("SELECT 1 FROM marts.rpt_rrhh_centro_mes WHERE mes = %s LIMIT 1", (mes,)).fetchone():
            raise RuntimeError(f"No hay datos de RRHH de {mes:%Y-%m} en el data warehouse "
                               "(¿se han cargado los Excel de ese mes y se ha ejecutado dbt?)")
        tiendas = conn.execute(
            "SELECT id_ubicacion, ubicacion FROM marts.dim_ubicacion WHERE tipo = 'tienda' ORDER BY ubicacion"
        ).fetchall()
        cadena = datos_cadena(conn, mes)
        rutas = [informe_tienda(conn, id_t, nombre, mes, carpeta, cadena) for id_t, nombre in tiendas]
        rutas.append(informe_rrhh(conn, mes, carpeta))
    return rutas


def ejecutar(fecha_proceso: date, resultado):
    """Paso 'informes' del ETL: solo el último día del mes (cuando el mes ya está completo)."""
    from registro import log
    if (fecha_proceso + timedelta(days=1)).day != 1:
        log.info("   No es fin de mes: no se generan informes")
        return
    rutas = generar(fecha_proceso)
    resultado.cargadas = len(rutas)
    log.info(f"   {len(rutas)} informes Excel en {rutas[0].parent.relative_to(RAIZ).as_posix()}/")


def main():
    parser = argparse.ArgumentParser(description="Genera los informes mensuales en Excel")
    parser.add_argument("--mes", required=True, type=lambda t: date.fromisoformat(t + "-01"), help="AAAA-MM")
    args = parser.parse_args()
    rutas = generar(args.mes)
    for ruta in rutas:
        print(f"  {ruta.relative_to(RAIZ).as_posix()}")
    print(f"{len(rutas)} informes generados")


if __name__ == "__main__":
    main()