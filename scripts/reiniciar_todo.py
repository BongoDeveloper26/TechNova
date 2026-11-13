"""
reiniciar_todo.py -> Borra TODOS los datos y regenera TechNova desde cero con un solo comando.

Sirve para:
  - dejar el proyecto como recién clonado después de muchas pruebas
  - regenerar todo tras cambiar la simulación (por ejemplo, NUM_CLIENTES en data_generator/config.py)

Qué hace, en orden:
   1. Borra las bases de datos technova (OLTP) y technova_dw (data warehouse) y crea la OLTP vacía
   2. Crea sus tablas, índices y vistas (los scripts de sql/init)
   3. Borra los ficheros generados: data/, informes/, models/ y dbt/target/
   4. Genera 3 años de datos simulados (data_generator)
   5. Simula los ficheros externos: CSV de proveedores de diciembre de 2025 y Excel de RRHH de 2025
   6. Ejecuta el ETL completo del 31/12/2025 (crea el data warehouse y lanza dbt)
   7. Genera los informes Excel de diciembre de 2025
   8. Entrena los modelos de Machine Learning

NO toca: la base de datos de Airflow, la configuración de Metabase (los dashboards siguen
funcionando, porque sus consultas leen el data warehouse por nombre) ni pgAdmin.

Requisitos: los contenedores encendidos (docker compose up -d) y el entorno virtual activado.
Conviene pausar los DAG en Airflow mientras se ejecuta, para que no lancen el ETL a la vez.

Uso:
    python scripts/reiniciar_todo.py               # pide confirmación
    python scripts/reiniciar_todo.py --si          # sin confirmación
    python scripts/reiniciar_todo.py --sin-ml      # sin entrenar los modelos
"""
import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import psycopg
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")

OLTP = os.getenv("POSTGRES_DB", "technova")
DW = os.getenv("DW_DB", "technova_dw")
CARPETAS_GENERADAS = ["data", "informes", "models", "dbt/target"]

# Lo que simula el "mundo exterior" y la fecha que procesa el ETL
FECHA_ETL = "2025-12-31"
PROVEEDORES = ("2025-12-01", "2025-12-31")
RRHH = ("2025-01", "2025-12")
MES_INFORMES = "2025-12"


def titulo(numero, texto):
    print(f"\n{'=' * 64}\n {numero}. {texto}\n{'=' * 64}", flush=True)


def conectar(base_datos):
    return psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"), port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=base_datos, user=os.getenv("POSTGRES_USER"), password=os.getenv("POSTGRES_PASSWORD"),
        autocommit=True,   # CREATE/DROP DATABASE no pueden ir dentro de una transacción
    )


def ejecutar(*argumentos):
    """Lanza un script del proyecto con el mismo Python (el del entorno virtual) y para si falla."""
    resultado = subprocess.run([sys.executable, *argumentos], cwd=RAIZ)
    if resultado.returncode != 0:
        sys.exit(f"\nHa fallado: python {' '.join(argumentos)}. El reinicio se ha detenido.")


def recrear_bases_de_datos():
    # Nos conectamos a la base "postgres" (la de mantenimiento): no se puede borrar
    # la base de datos a la que se está conectado
    with conectar("postgres") as conn:
        for base in (DW, OLTP):
            # WITH (FORCE) cierra antes las conexiones abiertas (Airflow, Metabase, pgAdmin...)
            conn.execute(f'DROP DATABASE IF EXISTS "{base}" WITH (FORCE)')
            print(f"   borrada {base}")
        conn.execute(f'CREATE DATABASE "{OLTP}"')
        print(f"   creada {OLTP} (vacía)")


def crear_esquema_oltp():
    with conectar(OLTP) as conn:
        for fichero in sorted((RAIZ / "sql" / "init").glob("*.sql")):
            conn.execute(fichero.read_text(encoding="utf-8"))
            print(f"   {fichero.name}")


def borrar_ficheros():
    for carpeta in CARPETAS_GENERADAS:
        ruta = RAIZ / carpeta
        if ruta.exists():
            shutil.rmtree(ruta)
            print(f"   borrada {carpeta}/")


def main():
    parser = argparse.ArgumentParser(description="Borra todos los datos y regenera TechNova desde cero")
    parser.add_argument("--si", action="store_true", help="No pedir confirmación")
    parser.add_argument("--sin-ml", action="store_true", help="No entrenar los modelos de Machine Learning")
    args = parser.parse_args()

    if not args.si:
        print(f"Se van a BORRAR las bases de datos '{OLTP}' y '{DW}' y las carpetas "
              f"{', '.join(c + '/' for c in CARPETAS_GENERADAS)}")
        if input("Escribe SI para continuar: ").strip() != "SI":
            sys.exit("Cancelado: no se ha borrado nada.")

    inicio = time.time()
    titulo(1, "Bases de datos")
    recrear_bases_de_datos()
    titulo(2, "Tablas, índices y vistas de la OLTP")
    crear_esquema_oltp()
    titulo(3, "Ficheros generados")
    borrar_ficheros()
    titulo(4, "Datos simulados")
    ejecutar("data_generator/main.py")
    titulo(5, "Ficheros externos (proveedores y RRHH)")
    ejecutar("etl/simular_proveedores.py", "--desde", PROVEEDORES[0], "--hasta", PROVEEDORES[1])
    ejecutar("etl/simular_rrhh.py", "--desde", RRHH[0], "--hasta", RRHH[1])
    titulo(6, f"ETL completo del {FECHA_ETL} (incluye dbt)")
    ejecutar("etl/run_etl.py", "--fecha", FECHA_ETL)
    titulo(7, "Informes Excel")
    ejecutar("etl/informes_excel.py", "--mes", MES_INFORMES)
    if not args.sin_ml:
        titulo(8, "Machine Learning")
        ejecutar("ml/segmentacion_clientes.py")
        ejecutar("ml/prevision_ventas.py")

    minutos, segundos = divmod(int(time.time() - inicio), 60)
    print(f"\nTechNova regenerada desde cero en {minutos} min {segundos} s.")
    print("Los dashboards de Metabase ya muestran los datos nuevos (si no, recarga la página).")
    print("Si pausaste los DAG de Airflow, ya puedes volver a activarlos.")


if __name__ == "__main__":
    main()