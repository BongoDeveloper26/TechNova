"""
Tests de los modelos de Machine Learning con datos sintéticos (sin base de datos).
"""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from prevision_ventas import CONFIANZA, MODELOS, backtest, black_friday, metricas, pesos
from segmentacion_clientes import SEGMENTOS, VARIABLES, nombrar, nombre_base


# ---------------------------------------------------------------------
# Segmentación
# ---------------------------------------------------------------------

def test_nombra_los_perfiles_tipicos():
    # Centroides estandarizados (0 = cliente medio)
    centroides = pd.DataFrame([
        [-0.9, 1.2, 1.5, 0.3, 0.0, -0.1],    # compran mucho y hace poco
        [0.1, -0.3, -0.4, 0.1, 0.4, 3.0],    # devuelven muchísimo
        [0.3, -0.5, -0.6, -0.4, -1.5, 0.0],  # casi solo en tienda y gastan poco
        [0.2, -0.4, -0.5, -0.5, 1.0, 0.0],   # casi solo web y gastan poco
    ], columns=VARIABLES)
    nombres = nombrar(centroides)
    assert [nombres[i] for i in range(4)] == ["VIP", "Devuelven mucho", "De tienda ocasionales",
                                              "Digitales de bajo gasto"]


def test_dos_grupos_iguales_no_repiten_nombre():
    centroides = pd.DataFrame([
        [0.5, -0.2, 0.4, 0.9, 0.1, 0.0],     # alto ticket, poco reciente
        [-0.6, -0.1, 0.2, 0.8, 0.1, 0.0],    # alto ticket, reciente
    ], columns=VARIABLES)
    nombres = list(nombrar(centroides).values())
    assert len(set(nombres)) == 2
    assert "Alto ticket ocasional (recientes)" in nombres


def test_cada_nombre_tiene_descripcion_y_accion():
    for nombre in ["VIP", "Alto ticket ocasional (recientes)", "Dormidos bis"]:
        assert nombre_base(nombre) in SEGMENTOS


# ---------------------------------------------------------------------
# Previsión de ventas
# ---------------------------------------------------------------------

@pytest.mark.parametrize("anio, esperado", [(2023, date(2023, 11, 24)), (2024, date(2024, 11, 29)),
                                            (2025, date(2025, 11, 28))])
def test_black_friday_es_el_ultimo_viernes_de_noviembre(anio, esperado):
    assert black_friday(anio).date() == esperado


def test_metricas():
    fechas = pd.date_range("2025-01-01", periods=4)
    real = pd.Series([100.0, 100.0, 100.0, 100.0], index=fechas)
    prevision = pd.Series([110.0, 90.0, 120.0, 100.0], index=fechas)
    m = metricas(real, prevision)
    assert m["wape"] == pytest.approx(40 / 400)          # suma de |errores| / suma real
    assert m["sesgo"] == pytest.approx(420 / 400 - 1)    # se pasa un 5 %


def test_pesos_por_recencia():
    fechas = pd.date_range("2025-01-01", periods=91)
    w = pesos(fechas, vida_media=90)
    assert w[-1] == pytest.approx(1.0) and w[0] == pytest.approx(0.5)
    assert pesos(fechas, None) is None


def serie_sintetica():
    """3 años de ventas diarias con crecimiento, semana y pico de noviembre."""
    fechas = pd.date_range("2023-01-01", "2025-12-31", freq="D")
    rng = np.random.default_rng(42)
    tendencia = np.linspace(1000, 3000, len(fechas))
    semana = np.where(fechas.day_of_week >= 5, 1.4, 1.0)
    noviembre = np.where(fechas.month == 11, 1.8, 1.0)
    return pd.Series(tendencia * semana * noviembre * rng.normal(1, 0.1, len(fechas)), index=fechas)


def test_backtest_compara_los_cuatro_modelos_sin_mirar_el_futuro():
    serie = serie_sintetica()
    real, previsiones, resultados = backtest(serie, festivos=set())
    assert set(resultados) == set(MODELOS)
    assert real.index.min() > serie.index.max() - pd.Timedelta(days=93)
    for m in MODELOS:
        assert previsiones[m].index.equals(real.index) and previsiones[m].notna().all()
    # Con un patrón tan claro, el modelo de ML tiene que ganar al ingenuo de las 4 semanas
    assert resultados["gradient_boosting"]["wape"] < resultados["media_4_semanas"]["wape"]
    assert 0 < CONFIANZA[0] < CONFIANZA[1] < 1
