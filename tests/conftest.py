"""
conftest.py -> pytest lo carga antes de los tests.

Los módulos del proyecto no son un paquete instalable: igual que hace Airflow con
PYTHONPATH, añadimos sus carpetas a la ruta de búsqueda de Python.
"""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
for carpeta in ("etl", "ml"):
    sys.path.insert(0, str(RAIZ / carpeta))
