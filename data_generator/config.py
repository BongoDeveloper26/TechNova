"""
config.py -> Parámetros generales de la simulación.

Cambiando estos valores puedes generar una TechNova más grande o más
pequeña sin tocar el resto del código.
"""
import os
from datetime import date

# Semilla aleatoria: con la misma semilla, siempre se generan los MISMOS datos.
# Así tus resultados son reproducibles (cualquiera que clone el repo obtiene lo mismo).
SEMILLA = 42

# Periodo de ventas simulado (3 años completos)
FECHA_INICIO = date(2023, 1, 1)
FECHA_FIN = date(2025, 12, 31)

# Tamaño de la simulación
# Se puede cambiar sin tocar el código con la variable de entorno TECHNOVA_NUM_CLIENTES
# (el CI de GitHub Actions la usa para generar una TechNova pequeña y rápida)
NUM_CLIENTES = int(os.getenv("TECHNOVA_NUM_CLIENTES", "40000"))

# Pedidos que hace de media un cliente al año (antes de aplicar la estacionalidad)
PEDIDOS_POR_CLIENTE_ANIO = 2.5
