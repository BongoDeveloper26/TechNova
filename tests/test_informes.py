"""
Tests de las utilidades de los informes Excel.
"""
from datetime import date

import pytest

from informes_excel import codigo, fin_de_mes, mes_anterior, nombre_mes, texto_excel


@pytest.mark.parametrize("texto, esperado", [
    ("TechNova Madrid Gran Vía", "technova_madrid_gran_via"),
    ("Almacén Noreste El Prat", "almacen_noreste_el_prat"),
    ("  A Coruña -- Centro ", "a_coruna_centro"),
])
def test_codigo_para_nombres_de_fichero(texto, esperado):
    assert codigo(texto) == esperado


def test_fechas_de_mes():
    assert mes_anterior(date(2025, 1, 1)) == date(2024, 12, 1)
    assert mes_anterior(date(2025, 3, 1), 3) == date(2024, 12, 1)
    assert fin_de_mes(date(2024, 2, 1)) == date(2024, 2, 29)     # año bisiesto
    assert fin_de_mes(date(2025, 12, 1)) == date(2025, 12, 31)
    assert nombre_mes(date(2025, 12, 1)) == "Diciembre 2025"


def test_texto_dentro_de_una_formula_de_excel():
    assert texto_excel('Tienda "centro"') == '"Tienda ""centro"""'
