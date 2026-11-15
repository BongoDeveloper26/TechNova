"""
Tests de la validación de los CSV de proveedores: cada fila mala se tiene que
rechazar con el motivo correcto, y las buenas tienen que pasar convertidas a euros.
"""
from datetime import date

import pandas as pd
import pytest

from configuracion import CONTRATOS_PROVEEDOR
from proveedores import a_numero, limpiar, validar

IBERIA = CONTRATOS_PROVEEDOR["iberia_tech"]          # formato español: 1.234,56 y fechas dd/mm/aaaa
PACIFIC = CONTRATOS_PROVEEDOR["pacific_electronics"]  # formato inglés y precios en dólares

CATALOGO = {"SKU-1": 100.0, "SKU-2": 50.0}            # coste conocido de cada producto (€)
TIPOS_CAMBIO = {(date(2025, 12, 1), "EUR"): 1.0, (date(2025, 12, 1), "USD"): 1.10}


def fila(sku="SKU-1", precio="100,00", moneda="EUR", stock="5", fecha="01/12/2025"):
    return {"sku": sku, "descripcion": "Producto", "precio_coste": precio, "moneda": moneda,
            "stock_disponible": stock, "plazo_entrega_dias": "3", "fecha_tarifa": fecha}


def procesar(filas, contrato=IBERIA):
    df = pd.DataFrame(filas)
    df.insert(0, "num_fila", range(2, len(df) + 2))
    return validar(limpiar(df, contrato), contrato, CATALOGO, TIPOS_CAMBIO)


def test_a_numero_formato_espanol_e_ingles():
    assert a_numero(pd.Series(["1.234,56"]), IBERIA).iloc[0] == pytest.approx(1234.56)
    assert a_numero(pd.Series(["1234.56"]), PACIFIC).iloc[0] == pytest.approx(1234.56)
    assert pd.isna(a_numero(pd.Series(["N/D"]), IBERIA).iloc[0])


def test_fila_correcta_pasa_y_se_limpia_el_sku():
    resultado = procesar([fila(sku=" sku-1 ")])
    assert resultado.loc[0, "motivo"] is None
    assert resultado.loc[0, "sku"] == "SKU-1"
    assert resultado.loc[0, "precio_coste_eur"] == pytest.approx(100.0)


@pytest.mark.parametrize("cambios, motivo", [
    ({"sku": ""}, "sku_vacio"),
    ({"sku": "NO-EXISTE"}, "sku_desconocido"),
    ({"fecha": "31/02/2025"}, "fecha_invalida"),
    ({"moneda": "USD"}, "moneda_incorrecta"),
    ({"precio": "consultar"}, "precio_no_numerico"),
    ({"precio": "-5,00"}, "precio_no_positivo"),
    ({"stock": "-1"}, "stock_invalido"),
    ({"precio": "10.000,00"}, "precio_anomalo"),     # error de tecleo x100
])
def test_cada_error_se_rechaza_con_su_motivo(cambios, motivo):
    assert procesar([fila(**cambios)]).loc[0, "motivo"] == motivo


def test_sku_repetido_se_queda_la_ultima_aparicion():
    resultado = procesar([fila(precio="90,00"), fila(sku="SKU-2", precio="50,00"), fila(precio="95,00")])
    assert list(resultado["motivo"]) == ["duplicado", None, None]


def test_conversion_a_euros_con_el_tipo_de_cambio_del_dia():
    filas = [fila(precio="110.00", moneda="USD", fecha="2025/12/01")]
    resultado = procesar(filas, PACIFIC)
    assert resultado.loc[0, "motivo"] is None
    assert resultado.loc[0, "precio_coste_eur"] == pytest.approx(100.0)   # 110 $ / 1,10


def test_sin_tipo_de_cambio_para_ese_dia():
    filas = [fila(precio="110.00", moneda="USD", fecha="2025/12/02")]
    assert procesar(filas, PACIFIC).loc[0, "motivo"] == "sin_tipo_cambio"
