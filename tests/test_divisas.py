"""
Tests de la transformación de la respuesta de la API de divisas: el BCE no publica tipos
de cambio en fin de semana, y el ETL tiene que rellenar esos días con el último valor.
"""
from datetime import date

import pytest

from divisas import transformar


def respuesta(*dias):
    """Respuesta de la API para los días indicados (USD, JPY y GBP)."""
    return [{"date": d, "base": "EUR", "quote": q, "rate": r}
            for d in dias for q, r in (("USD", 1.10), ("JPY", 160.0), ("GBP", 0.85))]


def test_rellena_el_fin_de_semana_con_el_viernes():
    # 2025-12-05 es viernes; 6 y 7 son sábado y domingo
    filas = transformar(respuesta("2025-12-05"), date(2025, 12, 5), date(2025, 12, 7))
    usd = {f[0]: f for f in filas if f[1] == "USD"}
    assert sorted(usd) == [date(2025, 12, 5), date(2025, 12, 6), date(2025, 12, 7)]
    assert usd[date(2025, 12, 6)][2] == pytest.approx(1.10)
    assert usd[date(2025, 12, 5)][3] is False     # dato real
    assert usd[date(2025, 12, 6)][3] is True      # dato rellenado (interpolado)


def test_el_euro_siempre_vale_uno():
    filas = transformar(respuesta("2025-12-05"), date(2025, 12, 5), date(2025, 12, 5))
    assert (date(2025, 12, 5), "EUR", 1.0, False, "fijo") in filas


def test_respuesta_que_no_es_una_lista():
    with pytest.raises(ValueError, match="Respuesta inesperada"):
        transformar({"error": "caída"}, date(2025, 12, 1), date(2025, 12, 2))


def test_tipo_de_cambio_negativo():
    datos = respuesta("2025-12-05")
    datos[0]["rate"] = -1
    with pytest.raises(ValueError, match="no válidos"):
        transformar(datos, date(2025, 12, 5), date(2025, 12, 5))
