"""
excel_estilos.py -> Piezas reutilizables para construir informes Excel con openpyxl.

informes_excel.py decide QUÉ va en cada informe; este módulo decide CÓMO se ve:
  - paleta de colores y formatos numéricos (un único sitio para cambiar el aspecto)
  - banda de título, tarjetas de indicadores (KPI), tablas de Excel con filtros
  - gráficos con los colores de la casa (barras, líneas, anillo, combinados)
  - celdas editables, nombres definidos, protección de hoja e impresión
"""
from datetime import datetime

from openpyxl.chart import BarChart, DoughnutChart, LineChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.chart.series import DataPoint
from openpyxl.drawing.text import CharacterProperties, ParagraphProperties
from openpyxl.formatting.rule import CellIsRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Protection, Side
from openpyxl.utils import get_column_letter
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo

# ---------------------------------------------------------------------
# Paleta
# ---------------------------------------------------------------------
AZUL_OSCURO = "1F3864"
AZUL = "2F5597"
AZUL_MEDIO = "8FAADC"
AZUL_CLARO = "D9E1F2"
GRIS_FONDO = "F2F2F2"
GRIS_BORDE = "D9D9D9"
GRIS_TEXTO = "7F7F7F"
VERDE = "548235"
ROJO = "C00000"
NARANJA = "ED7D31"
DORADO = "FFE699"
# Colores de las series de los gráficos, en orden
SERIES = ["2F5597", "ED7D31", "A5A5A5", "FFC000", "5B9BD5", "70AD47", "264478", "9E480E", "636363", "997300"]

# ---------------------------------------------------------------------
# Formatos numéricos (se guardan en el fichero en formato "inglés";
# Excel los muestra con la coma y el punto del idioma de cada usuario)
# ---------------------------------------------------------------------
EUROS = '#,##0.00 "€"'
EUROS_ENTERO = '#,##0 "€"'
PORCENTAJE = "0.0%"
ENTERO = "#,##0"
DECIMAL = "#,##0.0"
FECHA = "DD/MM/YYYY"
# Variación con flecha: positivo, negativo y cero tienen cada uno su formato
VARIACION = '"▲ "0.0%;"▼ "0.0%;"● "0.0%'
VARIACION_TEXTO = '"▲ "0.0%" vs mes anterior";"▼ "0.0%" vs mes anterior";"● sin cambios"'

RELLENO_VERDE = PatternFill("solid", fgColor="C6EFCE")
RELLENO_ROJO = PatternFill("solid", fgColor="FFC7CE")
RELLENO_EDITABLE = PatternFill("solid", fgColor="FFF2CC")
RELLENO_DESTACADO = PatternFill("solid", fgColor=DORADO)
RELLENO_GRIS = PatternFill("solid", fgColor=GRIS_FONDO)
FUENTE_VERDE = Font(bold=True, color=VERDE)
FUENTE_ROJA = Font(bold=True, color=ROJO)
FUENTE_EDITABLE = Font(bold=True, color="0000FF")   # convención financiera: azul = dato que se puede cambiar
LINEA_FINA = Side(style="thin", color=GRIS_BORDE)
CAJA = Border(left=LINEA_FINA, right=LINEA_FINA, top=LINEA_FINA, bottom=LINEA_FINA)


def relleno(color):
    return PatternFill("solid", fgColor=color)


# ---------------------------------------------------------------------
# Libro y hojas
# ---------------------------------------------------------------------

def propiedades(wb, titulo, asunto):
    wb.properties.creator = "TechNova Data Platform"
    wb.properties.title = titulo
    wb.properties.subject = asunto
    wb.properties.keywords = "TechNova, informe mensual, generado automáticamente"


def nombre_definido(wb, nombre, hoja, celda):
    """Da un nombre a una celda o rango (p. ej. ObjetivoVentas) para usarlo en fórmulas."""
    def absoluta(ref):   # "C12" -> "$C$12"
        letras = "".join(c for c in ref if c.isalpha())
        return f"${letras}${ref[len(letras):]}"
    hoja_ref = f"'{hoja}'"   # entre comillas siempre: admite espacios y tildes
    ref = f"{hoja_ref}!" + ":".join(absoluta(parte) for parte in celda.split(":"))
    wb.defined_names[nombre] = DefinedName(nombre, attr_text=ref)


def hoja_panel(ws, columnas=14, filas=70):
    """Hoja tipo 'cuadro de mando': fondo gris, sin cuadrícula, columnas iguales."""
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 2
    for c in range(2, columnas + 1):
        ws.column_dimensions[get_column_letter(c)].width = 11.5
    for fila in ws.iter_rows(min_row=1, max_row=filas, min_col=1, max_col=columnas + 1):
        for celda in fila:
            celda.fill = RELLENO_GRIS


def banda_titulo(ws, titulo, subtitulo, ultima_columna, fila=1):
    """Banda azul oscuro con el título y el subtítulo, y una línea con la fecha de generación."""
    ultima = get_column_letter(ultima_columna)
    ws.merge_cells(f"A{fila}:{ultima}{fila}")
    ws.merge_cells(f"A{fila + 1}:{ultima}{fila + 1}")
    for c in range(1, ultima_columna + 1):
        ws.cell(fila, c).fill = relleno(AZUL_OSCURO)
        ws.cell(fila + 1, c).fill = relleno(AZUL_OSCURO)
        ws.cell(fila + 2, c).fill = relleno(NARANJA)
    ws.cell(fila, 1, f"  TECHNOVA   |   {titulo}").font = Font(bold=True, size=18, color="FFFFFF")
    ws.cell(fila + 1, 1, f"  {subtitulo}").font = Font(bold=True, size=12, color=AZUL_MEDIO)
    ws.cell(fila, 1).alignment = Alignment(vertical="center")
    ws.cell(fila + 1, 1).alignment = Alignment(vertical="top")
    ws.row_dimensions[fila].height = 36
    ws.row_dimensions[fila + 1].height = 24
    ws.row_dimensions[fila + 2].height = 4
    nota = ws.cell(fila + 3, 1, f"  Generado automáticamente el {datetime.now():%d/%m/%Y a las %H:%M} "
                                 "desde el data warehouse de TechNova")
    nota.font = Font(italic=True, size=9, color=GRIS_TEXTO)


def titulo_seccion(ws, celda, texto, ancho=None):
    ws[celda] = texto
    ws[celda].font = Font(bold=True, size=12, color=AZUL_OSCURO)
    if ancho:
        fila = ws[celda].row
        for c in range(ws[celda].column, ws[celda].column + ancho):
            ws.cell(fila, c).border = Border(bottom=Side(style="medium", color=AZUL))


def nota(ws, celda, texto):
    ws[celda] = texto
    ws[celda].font = Font(italic=True, size=9, color=GRIS_TEXTO)


# ---------------------------------------------------------------------
# Tarjetas de indicadores (KPI)
# ---------------------------------------------------------------------

def tarjeta(ws, fila, columna, titulo, valor, formato, variacion=None, bueno_si_sube=True,
            pie=None, formato_pie=None, ancho=3, color=AZUL):
    """
    Tarjeta de 4 filas x `ancho` columnas:
        TÍTULO (pequeño, gris)
        VALOR (grande; normalmente una fórmula que apunta a otra hoja)
        variación con flecha en verde o rojo  -> o un pie de texto/fórmula
    """
    c1, c2 = columna, columna + ancho - 1
    for f in range(fila, fila + 4):
        for c in range(c1, c2 + 1):
            celda = ws.cell(f, c)
            celda.fill = relleno("FFFFFF")
            celda.border = Border(
                left=LINEA_FINA if c == c1 else None, right=LINEA_FINA if c == c2 else None,
                top=Side(style="thick", color=color) if f == fila else None,
                bottom=LINEA_FINA if f == fila + 3 else None)
    L1, L2 = get_column_letter(c1), get_column_letter(c2)
    ws.merge_cells(f"{L1}{fila}:{L2}{fila}")
    ws.merge_cells(f"{L1}{fila + 1}:{L2}{fila + 2}")
    ws.merge_cells(f"{L1}{fila + 3}:{L2}{fila + 3}")

    t = ws.cell(fila, c1, titulo.upper())
    t.font = Font(bold=True, size=9, color=GRIS_TEXTO)
    t.alignment = Alignment(horizontal="center", vertical="center")

    v = ws.cell(fila + 1, c1, valor)
    v.font = Font(bold=True, size=22, color=AZUL_OSCURO)
    v.number_format = formato
    v.alignment = Alignment(horizontal="center", vertical="center")

    p = ws.cell(fila + 3, c1)
    p.alignment = Alignment(horizontal="center", vertical="center")
    if variacion is not None:
        p.value = variacion
        p.number_format = VARIACION_TEXTO
        p.font = Font(bold=True, size=10, color=GRIS_TEXTO)
        bien, mal = (FUENTE_VERDE, FUENTE_ROJA) if bueno_si_sube else (FUENTE_ROJA, FUENTE_VERDE)
        ref = f"{L1}{fila + 3}"
        ws.conditional_formatting.add(ref, CellIsRule(operator="greaterThan", formula=["0.0005"], font=bien))
        ws.conditional_formatting.add(ref, CellIsRule(operator="lessThan", formula=["-0.0005"], font=mal))
    elif pie is not None:
        p.value = pie
        if formato_pie:
            p.number_format = formato_pie
        p.font = Font(size=10, color=GRIS_TEXTO)
    ws.row_dimensions[fila].height = 20
    ws.row_dimensions[fila + 3].height = 20
    return f"{L1}{fila + 1}"


# ---------------------------------------------------------------------
# Tablas
# ---------------------------------------------------------------------

def escribir_tabla(ws, fila, columnas, filas, nombre_tabla, formatos=None,
                   estilo="TableStyleMedium2", columna=1):
    """
    Escribe una tabla de Excel "de verdad" (con filtros y filas en bandas).
    filas: lista de listas; un texto que empieza por "=" es una fórmula y puede usar {r} (nº de fila).
    formatos: {índice de columna (desde 0): formato numérico}.
    Devuelve (primera fila de datos, última fila de datos).
    """
    for c, titulo in enumerate(columnas):
        celda = ws.cell(fila, columna + c, titulo)
        celda.alignment = Alignment(wrap_text=True, vertical="center")
        # La cabecera se pinta también a mano: así se ve igual en cualquier programa
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = relleno(AZUL_OSCURO if estilo == "TableStyleMedium2" else AZUL)
    for i, valores in enumerate(filas, start=1):
        r = fila + i
        for c, valor in enumerate(valores):
            if isinstance(valor, str) and valor.startswith("="):
                valor = valor.format(r=r)
            celda = ws.cell(r, columna + c, valor)
            if formatos and c in formatos:
                celda.number_format = formatos[c]
    ultima_fila = fila + max(len(filas), 1)
    rango = f"{get_column_letter(columna)}{fila}:{get_column_letter(columna + len(columnas) - 1)}{ultima_fila}"
    tabla = Table(displayName=nombre_tabla, ref=rango)
    tabla.tableStyleInfo = TableStyleInfo(name=estilo, showRowStripes=True)
    ws.add_table(tabla)
    ws.row_dimensions[fila].height = 32
    return fila + 1, ultima_fila


def fila_total(ws, fila, formulas, formatos, columna_titulo=1, texto="TOTAL"):
    """Fila de totales debajo de una tabla: {letra de columna: fórmula}."""
    ws.cell(fila, columna_titulo, texto)
    columnas = [columna_titulo] + [ws[f"{c}1"].column for c in formulas]
    for letra, formula in formulas.items():
        ws[f"{letra}{fila}"] = formula
        if letra in formatos:
            ws[f"{letra}{fila}"].number_format = formatos[letra]
    for c in range(min(columnas), max(columnas) + 1):
        celda = ws.cell(fila, c)
        celda.font = Font(bold=True, color=AZUL_OSCURO)
        celda.fill = relleno(AZUL_CLARO)
        celda.border = Border(top=Side(style="medium", color=AZUL_OSCURO))


def anchos(ws, columnas):
    for letra, ancho in columnas.items():
        ws.column_dimensions[letra].width = ancho


def celda_editable(ws, celda, valor, formato, minimo=0, mensaje="Introduce un número mayor que 0"):
    """Celda que el usuario PUEDE cambiar: amarilla, texto azul, desbloqueada y con validación."""
    ws[celda] = valor
    ws[celda].number_format = formato
    ws[celda].fill = RELLENO_EDITABLE
    ws[celda].font = FUENTE_EDITABLE
    ws[celda].border = CAJA
    ws[celda].protection = Protection(locked=False)
    validacion = DataValidation(type="decimal", operator="greaterThanOrEqual", formula1=str(minimo),
                                showErrorMessage=True, errorTitle="Valor no válido", error=mensaje)
    ws.add_data_validation(validacion)
    validacion.add(ws[celda])


def proteger(ws):
    """Protege la hoja (sin contraseña): solo se pueden editar las celdas desbloqueadas."""
    ws.protection.sheet = True
    ws.protection.formatCells = False
    ws.protection.formatColumns = False
    ws.protection.autoFilter = False
    ws.protection.sort = False


def destacar_si(ws, rango, formula, fill=RELLENO_DESTACADO, font=None):
    ws.conditional_formatting.add(rango, FormulaRule(formula=[formula], fill=fill, font=font))


def preparar_impresion(ws, titulo, filas_repetidas=None, una_pagina=False):
    """Horizontal, ajustado al ancho de la página, con pie de página y número de página."""
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1 if una_pagina else 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_options.horizontalCentered = True
    ws.page_margins.left = ws.page_margins.right = 0.4
    ws.page_margins.top = ws.page_margins.bottom = 0.6
    ws.oddFooter.left.text = f"TechNova · {titulo}"
    ws.oddFooter.left.size = 8
    ws.oddFooter.right.text = "Página &P de &N"
    ws.oddFooter.right.size = 8
    if filas_repetidas:
        ws.print_title_rows = filas_repetidas


# ---------------------------------------------------------------------
# Gráficos
# ---------------------------------------------------------------------

def _ejes_visibles(grafico):
    # openpyxl 3.1 marca los ejes como ocultos por defecto: hay que mostrarlos a mano
    grafico.x_axis.delete = False
    grafico.y_axis.delete = False


def _color_serie(serie, color, linea=False):
    if linea:
        serie.graphicalProperties.line.solidFill = color
        serie.graphicalProperties.line.width = 28575   # 2,25 pt
        serie.smooth = False
    else:
        serie.graphicalProperties.solidFill = color
        serie.graphicalProperties.line.solidFill = color


def _tamano(grafico, ancho, alto, titulo):
    grafico.title = titulo
    # Título en 12 pt y azul oscuro (por defecto sale enorme)
    grafico.title.tx.rich.p[0].pPr = ParagraphProperties(
        defRPr=CharacterProperties(sz=1200, b=True, solidFill=AZUL_OSCURO))
    grafico.visible_cells_only = False   # dibujar también datos de columnas ocultas
    grafico.width, grafico.height = ancho, alto
    grafico.style = 2


def barras(ws_datos, col_categorias, cols_valores, fila_cabecera, ultima_fila, titulo,
           horizontal=False, ancho=15, alto=7.5, formato_eje=None, colores=None, destacar=None,
           etiquetas=False, leyenda=False, apiladas=False):
    g = BarChart()
    g.type = "bar" if horizontal else "col"
    _tamano(g, ancho, alto, titulo)
    _ejes_visibles(g)
    if apiladas:
        g.grouping, g.overlap = "stacked", 100
    for i, col in enumerate(cols_valores):
        g.add_data(Reference(ws_datos, min_col=col, min_row=fila_cabecera, max_row=ultima_fila),
                   titles_from_data=True)
        _color_serie(g.series[-1], (colores or SERIES)[i % len(SERIES)])
    g.set_categories(Reference(ws_datos, min_col=col_categorias, min_row=fila_cabecera + 1, max_row=ultima_fila))
    if destacar is not None:   # una barra de otro color (p. ej. la tienda del informe)
        punto = DataPoint(idx=destacar)
        punto.graphicalProperties.solidFill = NARANJA
        punto.graphicalProperties.line.solidFill = NARANJA
        g.series[0].dPt.append(punto)
    if formato_eje:
        g.y_axis.number_format = formato_eje
    g.y_axis.majorGridlines = None if horizontal else g.y_axis.majorGridlines
    if horizontal:
        g.x_axis.scaling.orientation = "maxMin"   # la primera fila arriba
    if etiquetas:
        g.dataLabels = DataLabelList()
        g.dataLabels.showVal = True
        g.dataLabels.showSerName = g.dataLabels.showCatName = g.dataLabels.showLegendKey = False
        g.dataLabels.position = "outEnd"
    g.gapWidth = 60
    if not leyenda:
        g.legend = None
    else:
        g.legend.position = "b"
    return g


def lineas(ws_datos, col_categorias, cols_valores, fila_cabecera, ultima_fila, titulo,
           ancho=15, alto=7.5, formato_eje=None, colores=None, formato_categorias=None):
    g = LineChart()
    _tamano(g, ancho, alto, titulo)
    _ejes_visibles(g)
    for i, col in enumerate(cols_valores):
        g.add_data(Reference(ws_datos, min_col=col, min_row=fila_cabecera, max_row=ultima_fila),
                   titles_from_data=True)
        _color_serie(g.series[-1], (colores or SERIES)[i % len(SERIES)], linea=True)
    g.set_categories(Reference(ws_datos, min_col=col_categorias, min_row=fila_cabecera + 1, max_row=ultima_fila))
    if formato_eje:
        g.y_axis.number_format = formato_eje
    if formato_categorias:
        g.x_axis.number_format = formato_categorias
    g.legend.position = "b"
    return g


def combinado(ws_datos, col_categorias, col_barras, col_linea, fila_cabecera, ultima_fila, titulo,
              eje_secundario=False, ancho=15, alto=7.5, formato_barras=None, formato_linea=None,
              formato_categorias=None):
    """Barras + línea en el mismo gráfico (la línea puede ir en un segundo eje, a la derecha)."""
    b = BarChart()
    _tamano(b, ancho, alto, titulo)
    _ejes_visibles(b)
    b.add_data(Reference(ws_datos, min_col=col_barras, min_row=fila_cabecera, max_row=ultima_fila),
               titles_from_data=True)
    _color_serie(b.series[0], AZUL_MEDIO)
    b.set_categories(Reference(ws_datos, min_col=col_categorias, min_row=fila_cabecera + 1, max_row=ultima_fila))
    b.gapWidth = 40
    if formato_barras:
        b.y_axis.number_format = formato_barras
    if formato_categorias:
        b.x_axis.number_format = formato_categorias

    l = LineChart()
    l.add_data(Reference(ws_datos, min_col=col_linea, min_row=fila_cabecera, max_row=ultima_fila),
               titles_from_data=True)
    _color_serie(l.series[0], NARANJA, linea=True)
    if eje_secundario:
        l.y_axis.axId = 200
        l.y_axis.crosses = "max"
        l.y_axis.delete = False
        l.y_axis.majorGridlines = None
        if formato_linea:
            l.y_axis.number_format = formato_linea
    b += l
    b.legend.position = "b"
    return b


def anillo(ws_datos, col_categorias, col_valores, fila_cabecera, ultima_fila, titulo, ancho=11, alto=7.5):
    g = DoughnutChart(holeSize=55)
    _tamano(g, ancho, alto, titulo)
    g.add_data(Reference(ws_datos, min_col=col_valores, min_row=fila_cabecera, max_row=ultima_fila),
               titles_from_data=True)
    g.set_categories(Reference(ws_datos, min_col=col_categorias, min_row=fila_cabecera + 1, max_row=ultima_fila))
    for i in range(ultima_fila - fila_cabecera):
        punto = DataPoint(idx=i)
        punto.graphicalProperties.solidFill = SERIES[i % len(SERIES)]
        punto.graphicalProperties.line.solidFill = "FFFFFF"
        g.series[0].dPt.append(punto)
    g.dataLabels = DataLabelList()
    g.dataLabels.showPercent = True
    g.dataLabels.showVal = g.dataLabels.showCatName = g.dataLabels.showSerName = False
    g.dataLabels.showLeaderLines = False
    g.legend.position = "r"
    return g