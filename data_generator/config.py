"""
config.py -> Parámetros generales de la simulación.
 
Cambiando estos valores puedes generar una TechNova más grande o más
pequeña sin tocar el resto del código.
"""
from datetime import date
 
# Semilla aleatoria: con la misma semilla, siempre se generan los MISMOS datos.
# Así tus resultados son reproducibles (cualquiera que clone el repo obtiene lo mismo).
SEMILLA = 42
 
# Periodo de ventas simulado (3 años completos)
FECHA_INICIO = date(2023, 1, 1)
FECHA_FIN = date(2025, 12, 31)
 
# Tamaño de la simulación
NUM_CLIENTES = 5000