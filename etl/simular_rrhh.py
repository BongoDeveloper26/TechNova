"""
simular_rrhh.py -> Simula los Excel que llegan cada mes a Recursos Humanos.

Esto NO es parte del ETL: hace de "mundo exterior", como simular_proveedores.py.
Cada mes llegan 3 tipos de Excel, hechos a mano por personas distintas y
con los vicios típicos de los Excel reales:

  1. fichajes_<centro>_<AAAA-MM>.xlsx  (lo rellena el encargado de cada centro)
     - Título y celdas combinadas arriba; la cabecera NO está en la fila 1
     - Filas en blanco entre semanas y una fila de TOTAL al final
     - Fechas y horas unas veces como fecha/hora de Excel y otras como texto ("9:58", "09.58", "9h58")
     - La columna Horas es una FÓRMULA (sin valor calculado: no hay que fiarse de ella)
     - A veces falta el nº de empleado (hay que buscarlo por el nombre)
     - Errores: salida antes que la entrada, fichaje sin salida, filas repetidas...

  2. ausencias_<AAAA-MM>.xlsx  (RRHH, una hoja por centro)
     - Solo el nombre del empleado, sin su número
     - El tipo de ausencia escrito de mil maneras ("Vacaciones", "VAC", "IT", "Baja"...)

  3. nominas_<AAAA-MM>.xlsx  (la gestoría)
     - Cabecera en la fila 7, después del membrete de la gestoría
     - "Apellidos, Nombre" en vez de "Nombre Apellidos"
     - Algunos importes guardados como texto: "1.850,00 €"
     - Fila de TOTALES con fórmulas

Uso:
    python etl/simular_rrhh.py --desde 2025-01 --hasta 2025-12
"""
import argparse
import random
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from configuracion import RAIZ
from conexiones import conectar_oltp

CARPETA_RRHH = RAIZ / "data" / "landing" / "rrhh"

FESTIVOS = {(1, 1), (1, 6), (5, 1), (8, 15), (10, 12), (11, 1), (12, 6), (12, 8), (12, 25)}
MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto",
         "Septiembre", "Octubre", "Noviembre", "Diciembre"]

# Salario base mensual y si cobra comisión por ventas
SALARIO = {
    "Director general": 5200, "Encargado de tienda": 2300, "Jefe de almacén": 2100,
    "Vendedor": 1350, "Técnico": 1550, "Operario de almacén": 1300,
}
PRECIO_HORA_EXTRA = 15.0
COMISION_VENTAS = 0.01          # los vendedores cobran el 1 % de lo que venden
SS_EMPRESA = 0.31               # cotización de la empresa a la Seguridad Social (aproximada)

# Formas "creativas" de escribir cada tipo de ausencia
TIPOS_AUSENCIA = {
    "vacaciones": ["Vacaciones", "VACACIONES", "VAC", "vacaciones"],
    "baja_medica": ["Baja médica", "IT", "Baja", "baja medica"],
    "asuntos_propios": ["Asuntos propios", "AAPP", "Asuntos Propios"],
    "permiso": ["Permiso", "Permiso retribuido"],
}


def codigo(texto: str) -> str:
    """'TechNova Madrid Gran Vía' -> 'technova_madrid_gran_via'"""
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")


def meses_entre(desde: date, hasta: date):
    m = date(desde.year, desde.month, 1)
    while m <= hasta:
        yield m
        m = date(m.year + (m.month == 12), m.month % 12 + 1, 1)


def dias_del_mes(mes: date):
    d = mes
    while d.month == mes.month:
        yield d
        d += timedelta(days=1)


def es_festivo(d: date) -> bool:
    return (d.month, d.day) in FESTIVOS


# ---------------------------------------------------------------------
# Datos de la empresa
# ---------------------------------------------------------------------

def cargar_empresa():
    with conectar_oltp() as conn:
        empleados = conn.execute("""
            SELECT e.id_empleado, e.nombre, e.apellidos, e.puesto, e.id_ubicacion,
                   u.nombre, u.tipo, e.fecha_contratacion
            FROM oltp.empleado e JOIN oltp.ubicacion u USING (id_ubicacion)
            ORDER BY e.id_empleado
        """).fetchall()
        ventas = conn.execute("""
            SELECT pe.id_empleado, date_trunc('month', pe.fecha)::date,
                   SUM(l.cantidad * l.precio_unitario - l.descuento)
            FROM oltp.pedido pe JOIN oltp.linea_pedido l USING (id_pedido)
            WHERE pe.id_empleado IS NOT NULL AND pe.estado <> 'cancelado'
            GROUP BY 1, 2
        """).fetchall()
    return empleados, {(e, m): float(v) for e, m, v in ventas}


# ---------------------------------------------------------------------
# Planificación: turnos y ausencias
# ---------------------------------------------------------------------

def trabaja_ese_dia(emp, d: date, rng_emp) -> bool:
    id_emp, _, _, puesto, _, _, tipo, contratacion = emp
    if d < contratacion or es_festivo(d) or d.weekday() == 6:
        return False
    if tipo == "almacen" or puesto == "Director general":
        return d.weekday() < 5
    # En tienda se abre de lunes a sábado: cada empleado libra el lunes o el sábado
    libra = 0 if rng_emp.random() < 0.5 else 5
    return d.weekday() != libra


def planificar_ausencias(empleados, desde: date, hasta: date, rng):
    """Devuelve {id_empleado: [(tipo, inicio, fin), ...]} para todo el periodo."""
    ausencias = defaultdict(list)
    for emp in empleados:
        id_emp, tipo_centro = emp[0], emp[6]
        for anio in range(desde.year, hasta.year + 1):
            # Vacaciones de verano (2 semanas) y otra semana suelta. En tienda, nunca en campaña
            inicio = date(anio, rng.choice([7, 8, 9]), rng.randint(1, 14))
            ausencias[id_emp].append(("vacaciones", inicio, inicio + timedelta(days=13)))
            while True:
                inicio = date(anio, rng.randint(1, 11), rng.randint(1, 25))
                if not (tipo_centro == "tienda" and inicio.month == 11 and inicio.day >= 15):
                    break
            ausencias[id_emp].append(("vacaciones", inicio, inicio + timedelta(days=6)))
        for mes in meses_entre(desde, hasta):
            if rng.random() < 0.04:                                  # baja médica
                inicio = mes + timedelta(days=rng.randint(0, 25))
                ausencias[id_emp].append(("baja_medica", inicio, inicio + timedelta(days=rng.randint(1, 9))))
            if rng.random() < 0.06:                                  # asuntos propios
                d = mes + timedelta(days=rng.randint(0, 27))
                ausencias[id_emp].append(("asuntos_propios", d, d))
    return ausencias


def esta_ausente(ausencias_emp, d: date):
    return any(inicio <= d <= fin for _, inicio, fin in ausencias_emp)


def turno(emp, d: date, rng):
    """Devuelve (entrada, salida, pausa_min) de un día."""
    puesto, tipo = emp[3], emp[6]
    if puesto == "Director general":
        base_e, base_s, pausa = time(9, 0), time(18, 0), 60
    elif tipo == "almacen":
        base_e, base_s, pausa = ((time(8, 0), time(16, 30), 30) if puesto == "Jefe de almacén"
                                 else (time(6, 0), time(14, 30), 30))
    else:
        base_e, base_s, pausa = rng.choice([(time(10, 0), time(18, 30), 30), (time(12, 30), time(21, 0), 30)])

    entrada = datetime.combine(d, base_e) + timedelta(minutes=rng.randint(-10, 8))
    salida = datetime.combine(d, base_s) + timedelta(minutes=rng.randint(-5, 15))
    # Horas extra: más probables en Black Friday y en las semanas antes de Navidad
    campania = (d.month == 11 and d.day >= 20) or (d.month == 12 and 10 <= d.day <= 31)
    if rng.random() < (0.45 if campania else 0.07):
        salida += timedelta(minutes=rng.choice([60, 90, 120, 150]))
    return entrada.time().replace(second=0), salida.time().replace(second=0), pausa


def horas_trabajadas(entrada: time, salida: time, pausa: int) -> float:
    minutos = (salida.hour * 60 + salida.minute) - (entrada.hour * 60 + entrada.minute) - pausa
    return round(minutos / 60, 2)


# ---------------------------------------------------------------------
# Escritura de los Excel
# ---------------------------------------------------------------------

NEGRITA = Font(bold=True)
TITULO = Font(bold=True, size=14)
GRIS = PatternFill("solid", fgColor="D9D9D9")


def hora_sucia(t: time, rng):
    """Casi siempre una hora de Excel; a veces texto escrito a mano."""
    r = rng.random()
    if r < 0.04:
        return f"{t.hour}:{t.minute:02d}"
    if r < 0.07:
        return f"{t.hour:02d}.{t.minute:02d}"
    if r < 0.09:
        return f"{t.hour}h{t.minute:02d}"
    return t


def escribir_fichajes(centro, mes, filas, rng):
    wb = Workbook()
    ws = wb.active
    ws.title = "Fichajes"
    ws["A1"] = "TECHNOVA - REGISTRO DE JORNADA"
    ws["A1"].font = TITULO
    ws.merge_cells("A1:H1")
    ws["A2"] = f"Centro: {centro}"
    ws["E2"] = f"Mes: {MESES[mes.month - 1]} {mes.year}"
    ws["A2"].font = ws["E2"].font = NEGRITA
    cabecera = ["Fecha", "Nº empleado", "Empleado", "Entrada", "Salida", "Pausa (min)", "Horas", "Observaciones"]
    ws.append([])
    ws.append(cabecera)                                    # fila 4
    for c in ws[4]:
        c.font, c.fill = NEGRITA, GRIS

    semana_anterior = None
    for fecha, emp_id, nombre, entrada, salida, pausa, obs in filas:
        if semana_anterior is not None and fecha.isocalendar()[1] != semana_anterior:
            ws.append([])                                  # fila en blanco entre semanas
        semana_anterior = fecha.isocalendar()[1]
        fecha_celda = fecha.strftime("%d/%m/%Y") if rng.random() < 0.08 else fecha
        n = ws.max_row + 1
        ws.append([fecha_celda, emp_id, nombre,
                   hora_sucia(entrada, rng) if entrada else None,
                   hora_sucia(salida, rng) if salida else None,
                   pausa, f"=(E{n}-D{n})*24-F{n}/60", obs])
        ws.cell(n, 1).number_format = "DD/MM/YYYY"
        ws.cell(n, 4).number_format = ws.cell(n, 5).number_format = "HH:MM"
        ws.cell(n, 7).number_format = "0.00"

    ultima = ws.max_row
    ws.append(["TOTAL", None, None, None, None, None, f"=SUM(G5:G{ultima})", None])
    ws.cell(ws.max_row, 1).font = ws.cell(ws.max_row, 7).font = NEGRITA
    for col, ancho in zip("ABCDEFGH", [12, 12, 32, 9, 9, 11, 8, 20]):
        ws.column_dimensions[col].width = ancho
    return wb


def escribir_ausencias(mes, por_centro):
    wb = Workbook()
    wb.remove(wb.active)
    for centro, filas in por_centro.items():
        ws = wb.create_sheet(centro[:31])                  # Excel no admite nombres de hoja de más de 31 caracteres
        ws.append(["Empleado", "Tipo", "Desde", "Hasta", "Días laborables", "Comentario"])
        for c in ws[1]:
            c.font, c.fill = NEGRITA, GRIS
        for nombre, tipo_txt, inicio, fin, comentario in filas:
            n = ws.max_row + 1
            ws.append([nombre, tipo_txt, inicio, fin, f"=NETWORKDAYS(C{n},D{n})", comentario])
            ws.cell(n, 3).number_format = ws.cell(n, 4).number_format = "DD/MM/YYYY"
        ws.column_dimensions["A"].width = 32
        ws.column_dimensions["B"].width = 18
    return wb


def importe_sucio(valor, rng):
    if rng.random() < 0.08:                                # importe escrito como texto
        entero, decimales = f"{valor:,.2f}".split(".")
        return f"{entero.replace(',', '.')},{decimales} €"
    return round(valor, 2)


def escribir_nominas(mes, filas, rng):
    wb = Workbook()
    ws = wb.active
    ws.title = "Nóminas"
    ws["A1"] = "ASESORÍA LABORAL GARCÍA & ASOCIADOS, S.L."
    ws["A1"].font = TITULO
    ws["A2"] = "Cliente: TechNova Retail S.L."
    ws["A3"] = f"Resumen de nóminas - {MESES[mes.month - 1]} {mes.year}"
    ws["A4"] = f"Fecha de emisión: {(mes + timedelta(days=32)).replace(day=1).strftime('%d/%m/%Y')}"
    cabecera = ["Nº Empleado", "Apellidos, Nombre", "Categoría", "Salario base", "Plus ventas",
                "Horas extra", "Importe horas extra", "Total devengado", "SS empresa", "Coste total"]
    ws.append([])
    ws.append([])
    ws.append(cabecera)                                    # fila 7
    for c in ws[7]:
        c.font, c.fill = NEGRITA, GRIS
    for f in filas:
        ws.append([f[0], f[1], f[2]] + [importe_sucio(v, rng) for v in f[3:5]] + [f[5]]
                  + [importe_sucio(v, rng) for v in f[6:]])
        for col in (4, 5, 7, 8, 9, 10):
            ws.cell(ws.max_row, col).number_format = '#,##0.00 "€"'
    ultima = ws.max_row
    ws.append(["TOTALES", None, None] + [f"=SUM({c}8:{c}{ultima})" for c in "DEFGHIJ"])
    for c in ws[ws.max_row]:
        c.font = NEGRITA
    ws.column_dimensions["B"].width = 34
    ws.column_dimensions["C"].width = 22
    return wb


# ---------------------------------------------------------------------
# Generación de un mes
# ---------------------------------------------------------------------

def generar_mes(mes, empleados, ventas, ausencias):
    rng = random.Random(f"rrhh-{mes}")                     # reproducible: mismo mes -> mismos ficheros
    carpeta = CARPETA_RRHH / mes.strftime("%Y-%m")
    carpeta.mkdir(parents=True, exist_ok=True)
    horas_extra = defaultdict(float)
    por_centro = defaultdict(list)
    for emp in empleados:
        por_centro[emp[5]].append(emp)

    # 1) Fichajes: un Excel por centro
    for centro, plantilla in por_centro.items():
        filas = []
        for d in dias_del_mes(mes):
            for emp in plantilla:
                rng_emp = random.Random(f"turno-{emp[0]}-{d.isocalendar()[1]}")
                if not trabaja_ese_dia(emp, d, rng_emp) or esta_ausente(ausencias[emp[0]], d):
                    continue
                entrada, salida, pausa = turno(emp, d, rng)
                horas_extra[emp[0]] += max(horas_trabajadas(entrada, salida, pausa) - 8, 0)
                nombre = f"{emp[1]} {emp[2]}"
                emp_id, obs = emp[0], None
                r = rng.random()
                if r < 0.05:
                    emp_id = None                                         # sin nº de empleado
                elif r < 0.07:
                    nombre = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode().upper()
                    emp_id = None                                         # en mayúsculas y sin tildes
                elif r < 0.073:
                    nombre, emp_id = f"{emp[1]} {emp[2].split()[0]}x", None   # nombre mal escrito
                r = rng.random()
                if r < 0.005:
                    entrada, salida = salida, entrada                     # entrada y salida al revés
                elif r < 0.01:
                    salida, obs = None, "Olvidó fichar la salida"
                filas.append((d, emp_id, nombre, entrada, salida, pausa, obs))
                if rng.random() < 0.005:
                    filas.append(filas[-1])                               # fila repetida
        escribir_fichajes(centro, mes, filas, rng).save(carpeta / f"fichajes_{codigo(centro)}_{mes:%Y-%m}.xlsx")

    # 2) Ausencias: un Excel con una hoja por centro (la parte de cada ausencia que cae en este mes)
    fin_mes = (mes + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    hojas = {centro: [] for centro in por_centro}
    for emp in empleados:
        for tipo, inicio, fin in ausencias[emp[0]]:
            if fin < mes or inicio > fin_mes or fin < emp[7]:
                continue
            desde, hasta = max(inicio, mes, emp[7]), min(fin, fin_mes)
            if rng.random() < 0.01:
                desde, hasta = hasta + timedelta(days=3), desde           # fechas al revés
            hojas[emp[5]].append((f"{emp[1]} {emp[2]}", rng.choice(TIPOS_AUSENCIA[tipo]),
                                  desde, hasta, "Justificante entregado" if tipo == "baja_medica" else None))
    escribir_ausencias(mes, hojas).save(carpeta / f"ausencias_{mes:%Y-%m}.xlsx")

    # 3) Nóminas de la gestoría
    filas = []
    for emp in empleados:
        if emp[7] > fin_mes:
            continue
        base = SALARIO[emp[3]]
        plus = round(ventas.get((emp[0], mes), 0) * COMISION_VENTAS, 2) if emp[3] == "Vendedor" else 0.0
        hx = round(horas_extra[emp[0]], 2)
        importe_hx = round(hx * PRECIO_HORA_EXTRA, 2)
        devengado = round(base + plus + importe_hx, 2)
        if rng.random() < 0.01:
            devengado += 100                                              # error de la gestoría: no cuadra
        ss = round(devengado * SS_EMPRESA, 2)
        filas.append((emp[0], f"{emp[2]}, {emp[1]}", emp[3], base, plus, hx, importe_hx,
                      devengado, ss, round(devengado + ss, 2)))
    escribir_nominas(mes, filas, rng).save(carpeta / f"nominas_{mes:%Y-%m}.xlsx")
    return len(por_centro) + 2


def simular(desde: date, hasta: date) -> int:
    empleados, ventas = cargar_empresa()
    # Las ausencias se planifican con una semilla fija por año, para que un mismo mes
    # salga igual tanto si se genera solo como dentro de un rango
    ausencias = defaultdict(list)
    for anio in range(desde.year, hasta.year + 1):
        plan = planificar_ausencias(empleados, date(anio, 1, 1), date(anio, 12, 31), random.Random(f"aus-{anio}"))
        for k, v in plan.items():
            ausencias[k].extend(v)
    return sum(generar_mes(mes, empleados, ventas, ausencias) for mes in meses_entre(desde, hasta))


def simular_mes_si_falta(mes: date) -> int:
    """
    Para Airflow: genera los Excel de un mes solo si todavía no existen.
    (Volver a generarlos cambiaría su hash y el ETL los recargaría sin necesidad)
    """
    mes = mes.replace(day=1)
    if (CARPETA_RRHH / mes.strftime("%Y-%m")).exists():
        return 0
    return simular(mes, mes)


def main():
    parser = argparse.ArgumentParser(description="Simula los Excel mensuales de RRHH")
    mes = lambda texto: date.fromisoformat(texto + "-01")  # noqa: E731  "2025-03" -> 2025-03-01
    parser.add_argument("--desde", type=mes, required=True, help="Primer mes, AAAA-MM")
    parser.add_argument("--hasta", type=mes, required=True, help="Último mes, AAAA-MM")
    args = parser.parse_args()
    total = simular(args.desde, args.hasta)
    print(f"{total} ficheros Excel generados en {CARPETA_RRHH.relative_to(RAIZ).as_posix()}/")


if __name__ == "__main__":
    sys.exit(main())