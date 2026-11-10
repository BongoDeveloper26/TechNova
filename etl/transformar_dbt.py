"""
transformar_dbt.py -> Lanza dbt (la "T" del ELT) desde Python.

Por qué un script en vez de llamar a dbt directamente:
  - dbt NO lee el archivo .env, y aquí lo cargamos antes de lanzarlo.
  - Siempre le pasa la carpeta del proyecto y del perfil, estés donde estés.
  - Lee el resultado (target/run_results.json) y lo resume para el registro del ETL.

Uso desde la terminal (cualquier comando de dbt):
    python etl/transformar_dbt.py build          # construye todo y pasa los tests
    python etl/transformar_dbt.py test           # solo los tests
    python etl/transformar_dbt.py docs generate  # genera la documentación
    python etl/transformar_dbt.py docs serve --port 8081

dbt puede estar instalado en otro entorno de Python (en Docker lo está):
en ese caso se indica su ruta con la variable de entorno DBT_BIN.
"""
import json
import os
import shutil
import subprocess
import sys
from collections import Counter

from dotenv import load_dotenv

from configuracion import RAIZ

CARPETA_DBT = RAIZ / "dbt"
RESULTADOS = CARPETA_DBT / "target" / "run_results.json"


def binario_dbt() -> str:
    ruta = os.getenv("DBT_BIN") or shutil.which("dbt")
    if not ruta:
        raise RuntimeError("No se encuentra dbt. Instálalo con: pip install dbt-core dbt-postgres")
    return ruta


def lanzar(argumentos, capturar=False) -> subprocess.CompletedProcess:
    load_dotenv(RAIZ / ".env")
    entorno = os.environ.copy()
    if capturar:
        entorno["DBT_USE_COLORS"] = "false"   # sin códigos de color en el log del ETL
    comando = [binario_dbt(), *argumentos,
               "--project-dir", str(CARPETA_DBT), "--profiles-dir", str(CARPETA_DBT)]
    return subprocess.run(comando, cwd=CARPETA_DBT, env=entorno,
                          capture_output=capturar, text=True, encoding="utf-8", errors="replace")


def resumir_resultados():
    """Cuenta modelos, tests... y su estado a partir de target/run_results.json."""
    datos = json.loads(RESULTADOS.read_text(encoding="utf-8"))
    conteo = Counter()
    fallos = []
    for r in datos["results"]:
        tipo = r["unique_id"].split(".")[0]       # model, test, seed, snapshot
        conteo[(tipo, r["status"])] += 1
        if r["status"] in ("error", "fail"):
            fallos.append(f"{tipo} {r['unique_id'].split('.')[2]}: {r['status']}")  # test.technova.<nombre>.<hash>
    return conteo, fallos


def ejecutar(resultado):
    """Paso 'dbt' del ETL: dbt build (seeds + modelos + snapshots + tests)."""
    from registro import log

    proceso = lanzar(["build"], capturar=True)
    for linea in proceso.stdout.splitlines():
        if " of " in linea or "Done." in linea:   # las líneas de progreso de dbt
            log.info(f"   dbt | {linea.split('  ', 1)[-1].strip()}")

    if not RESULTADOS.exists():
        raise RuntimeError(f"dbt no ha llegado a ejecutarse:\n{proceso.stdout[-2000:]}{proceso.stderr[-2000:]}")

    conteo, fallos = resumir_resultados()
    construidos = sum(n for (tipo, estado), n in conteo.items()
                      if tipo in ("model", "seed", "snapshot") and estado == "success")
    tests_ok = conteo[("test", "pass")]
    tests_mal = conteo[("test", "fail")] + conteo[("test", "error")]

    resultado.leidas = sum(conteo.values())
    resultado.cargadas = construidos
    resultado.rechazadas = tests_mal
    log.info(f"   dbt: {construidos} objetos construidos | tests: {tests_ok} ok, {tests_mal} fallidos"
             f" | avisos: {conteo[('test', 'warn')]}")

    if proceso.returncode != 0:
        raise RuntimeError("dbt build ha fallado:\n" + "\n".join(fallos or [proceso.stdout[-1500:]]))


if __name__ == "__main__":
    argumentos = sys.argv[1:] or ["build"]
    sys.exit(lanzar(argumentos).returncode)