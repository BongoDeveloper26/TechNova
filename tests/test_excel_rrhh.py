"""
Tests de la limpieza de los Excel de RRHH: los valores llegan escritos "a mano" de muchas formas
y todos tienen que acabar en el mismo dato limpio (o rechazarse con su motivo).
"""
from datetime import date, datetime, time

import pytest

from excel_rrhh import FilaInvalida, a_entero, a_fecha, a_hora, a_importe, normalizar


@pytest.mark.parametrize("texto, esperado", [
    ("  José   GARCÍA ", "jose garcia"),
    ("Nélida Casanovas Pérez", "nelida casanovas perez"),
    ("ÁLVARO\tROSSELLÓ", "alvaro rossello"),
])
def test_normalizar_quita_tildes_mayusculas_y_espacios(texto, esperado):
    assert normalizar(texto) == esperado


@pytest.mark.parametrize("valor", [
    datetime(2025, 3, 7, 10, 30),   # celda con fecha y hora
    date(2025, 3, 7),               # celda con fecha
    45723,                          # número de serie de Excel
    "07/03/2025", "2025-03-07", "07-03-2025", "07.03.2025", "  07/03/2025 ",
])
def test_a_fecha_entiende_todos_los_formatos(valor):
    assert a_fecha(valor) == date(2025, 3, 7)


@pytest.mark.parametrize("valor", ["32/01/2025", "ayer", "", None, 12])
def test_a_fecha_rechaza_lo_que_no_es_una_fecha(valor):
    with pytest.raises(FilaInvalida, match="fecha_invalida"):
        a_fecha(valor)


@pytest.mark.parametrize("valor, esperado", [
    ("9:58", time(9, 58)), ("09.58", time(9, 58)), ("9h58", time(9, 58)),
    ("9h", time(9, 0)), ("9", time(9, 0)), (" 18:05 ", time(18, 5)),
    (0.5, time(12, 0)),                             # fracción del día de Excel
    (time(8, 30, 45), time(8, 30)),                 # se ignoran los segundos
    (datetime(2025, 1, 1, 17, 15), time(17, 15)),
])
def test_a_hora_entiende_todos_los_formatos(valor, esperado):
    assert a_hora(valor) == esperado


@pytest.mark.parametrize("valor", ["25:00", "9:5x", "mañana", 1.5])
def test_a_hora_rechaza_horas_imposibles(valor):
    with pytest.raises(FilaInvalida, match="hora_invalida"):
        a_hora(valor)


@pytest.mark.parametrize("valor, esperado", [
    (1850, 1850.0), (1850.5, 1850.5), ("1.850,00 €", 1850.0),
    ("1850,5", 1850.5), ("2\xa0300,10 €", 2300.10),
])
def test_a_importe_entiende_el_formato_espanol(valor, esperado):
    assert a_importe(valor) == pytest.approx(esperado)


def test_a_importe_rechaza_texto():
    with pytest.raises(FilaInvalida, match="importe_invalido"):
        a_importe("mil euros")


def test_a_entero():
    assert a_entero("12") == 12
    assert a_entero(7.0) == 7
    assert a_entero("") is None and a_entero(None) is None
    with pytest.raises(FilaInvalida):
        a_entero("doce")
