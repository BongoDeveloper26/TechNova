"""
crear_dashboard.py -> Crea los dashboards de TechNova en Metabase a través de su API.

"Dashboards como código": en vez de construirlos a mano con clics, se definen
en dashboards.py y este script los crea. Ventajas:
  - Están en Git: se ve qué ha cambiado y cuándo.
  - Cualquiera que clone el repo obtiene los mismos dashboards con un comando.
  - Si alguien rompe un gráfico, se vuelve a ejecutar el script y queda como estaba.

Lo que hace, en orden:
  1. Espera a que Metabase esté arrancado            GET  /api/health
  2. Primera vez: crea el usuario administrador      POST /api/setup
     Siguientes: inicia sesión                       POST /api/session
  3. Conecta Metabase con technova_dw                POST /api/database
  4. Crea (o actualiza) cada gráfico                 POST/PUT /api/card
  5. Crea cada dashboard y coloca los gráficos       POST /api/dashboard + PUT /api/dashboard/:id

Se puede ejecutar varias veces: si algo ya existe (mismo nombre), lo actualiza.

Uso (con Docker en marcha):
    python dashboard/crear_dashboard.py
"""
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

from dashboards import DASHBOARDS

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")

URL = os.getenv("METABASE_URL", "http://localhost:3000")
ADMIN_EMAIL = os.getenv("METABASE_ADMIN_EMAIL", "admin@technova.com")
ADMIN_PASSWORD = os.getenv("METABASE_ADMIN_PASSWORD", "TechNova2025!")
NOMBRE_BD = "TechNova DW"
COLECCION = "TechNova"


class Metabase:
    """Pequeño cliente de la API REST de Metabase."""

    def __init__(self, url):
        self.url = url.rstrip("/")
        self.sesion = requests.Session()

    def _llamar(self, metodo, ruta, **kwargs):
        respuesta = self.sesion.request(metodo, f"{self.url}/api/{ruta}", timeout=60, **kwargs)
        if respuesta.status_code >= 400:
            raise RuntimeError(f"{metodo} /api/{ruta} -> {respuesta.status_code}: {respuesta.text[:500]}")
        return respuesta.json() if respuesta.content else None

    def get(self, ruta, **kw):
        return self._llamar("GET", ruta, **kw)

    def post(self, ruta, datos):
        # La base de datos interna de Metabase (H2) a veces se queda con el contador de ids
        # desincronizado y propone un id que ya existe. Cada intento fallido lo hace avanzar,
        # así que basta con reintentar hasta dar con un id libre.
        for intento in range(20):
            try:
                return self._llamar("POST", ruta, json=datos)
            except RuntimeError as error:
                if "primary key violation" not in str(error).lower() or intento == 19:
                    raise

    def put(self, ruta, datos):
        return self._llamar("PUT", ruta, json=datos)

    # ------------------------------------------------------------------

    def esperar_arranque(self, minutos=5):
        print(f"Esperando a Metabase en {self.url} ...")
        limite = time.time() + minutos * 60
        while time.time() < limite:
            try:
                if requests.get(f"{self.url}/api/health", timeout=5).status_code == 200:
                    print("  Metabase listo")
                    return
            except requests.ConnectionError:
                pass
            time.sleep(5)
        raise RuntimeError("Metabase no responde. ¿Está en marcha el contenedor technova_metabase?")

    def iniciar_sesion(self):
        propiedades = self.get("session/properties")
        if not propiedades.get("has-user-setup"):
            print("  Primera vez: creando el usuario administrador")
            respuesta = self.post("setup", {
                "token": propiedades["setup-token"],
                "user": {"first_name": "Admin", "last_name": "TechNova",
                         "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                "prefs": {"site_name": "TechNova", "site_locale": "es", "allow_tracking": False},
            })
        else:
            respuesta = self.post("session", {"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        self.sesion.headers["X-Metabase-Session"] = respuesta["id"]
        print(f"  Sesión iniciada como {ADMIN_EMAIL}")

    def buscar_en_coleccion(self, id_coleccion, modelo, nombre):
        """
        Devuelve el id del objeto (card o dashboard) con ese nombre dentro de la colección, o None.
        Se lista la colección en vez de usar el buscador: el buscador se actualiza en
        segundo plano y algo recién creado podría no aparecer todavía.
        """
        respuesta = self.get(f"collection/{id_coleccion}/items", params={"models": modelo})
        elementos = respuesta.get("data", []) if isinstance(respuesta, dict) else respuesta
        for e in elementos:
            if e.get("model") == modelo and e.get("name") == nombre and not e.get("archived"):
                return e["id"]
        return None


# ----------------------------------------------------------------------
# Base de datos y colección
# ----------------------------------------------------------------------

def datos_conexion():
    return {
        # Metabase está dentro de Docker: PostgreSQL se llama "postgres", no "localhost"
        "host": "postgres",
        "port": 5432,
        "dbname": os.getenv("DW_DB", "technova_dw"),
        "user": os.getenv("POSTGRES_USER"),
        "password": os.getenv("POSTGRES_PASSWORD"),
    }


def conectar_base_de_datos(mb):
    respuesta = mb.get("database")
    lista = respuesta.get("data", []) if isinstance(respuesta, dict) else respuesta
    for bd in lista:
        if bd["name"] == NOMBRE_BD:
            # Se actualizan los datos de conexión por si ha cambiado la contraseña del .env
            mb.put(f"database/{bd['id']}", {"engine": "postgres", "details": datos_conexion()})
            print(f"  Base de datos '{NOMBRE_BD}' ya conectada (id {bd['id']}): conexión actualizada")
            return bd["id"]
    bd = mb.post("database", {"name": NOMBRE_BD, "engine": "postgres", "details": datos_conexion()})
    print(f"  Base de datos '{NOMBRE_BD}' conectada (id {bd['id']})")
    return bd["id"]


def preparar_coleccion(mb):
    """Una carpeta en Metabase para tener todo lo de TechNova junto."""
    respuesta = mb.get("collection")
    colecciones = respuesta.get("data", []) if isinstance(respuesta, dict) else respuesta
    for c in colecciones:
        if c.get("name") == COLECCION and not c.get("archived"):
            return c["id"]
    return mb.post("collection", {"name": COLECCION, "parent_id": None})["id"]


# ----------------------------------------------------------------------
# Gráficos (cards)
# ----------------------------------------------------------------------

def ajustes_visuales(tarjeta):
    """Traduce la definición de dashboards.py a los 'visualization_settings' de Metabase."""
    ajustes = {"column_settings": {}}
    tipo = tarjeta["tipo"]

    if "ejes" in tarjeta:
        dimensiones, metricas = tarjeta["ejes"]
        if tipo == "pie":
            ajustes["pie.dimension"] = dimensiones[0]
            ajustes["pie.metric"] = metricas[0]
        else:
            ajustes["graph.dimensions"] = dimensiones
            ajustes["graph.metrics"] = metricas
            # Números encima de las barras solo si hay una única serie (si no, se amontonan)
            ajustes["graph.show_values"] = tipo in ("bar", "row") and len(dimensiones) == 1 and len(metricas) == 1
            # Un único eje Y aunque haya dos métricas (Metabase los separa por defecto)
            ajustes["graph.y_axis.auto_split"] = False
            # No agrupar las últimas categorías en una barra "Other"
            ajustes["graph.max_categories_enabled"] = False
            ajustes["graph.max_categories"] = 50   # las barras horizontales agrupan aunque se desactive

    for columna in tarjeta.get("euros", []):
        ajustes["column_settings"][f'["name","{columna}"]'] = {
            "number_style": "currency", "currency": "EUR", "currency_style": "symbol", "decimals": 0}
    for columna in tarjeta.get("porcentaje", []):
        ajustes["column_settings"][f'["name","{columna}"]'] = {"number_style": "percent", "decimals": 1}
    return ajustes


def crear_o_actualizar_tarjeta(mb, tarjeta, id_bd, id_coleccion):
    datos = {
        "name": tarjeta["nombre"],
        "type": "question",
        "display": tarjeta["tipo"],
        "collection_id": id_coleccion,
        "dataset_query": {"database": id_bd, "type": "native", "native": {"query": tarjeta["sql"].strip()}},
        "visualization_settings": ajustes_visuales(tarjeta),
    }
    id_tarjeta = mb.buscar_en_coleccion(id_coleccion, "card", tarjeta["nombre"])
    if id_tarjeta:
        mb.put(f"card/{id_tarjeta}", datos)
        return id_tarjeta, "actualizada"
    return mb.post("card", datos)["id"], "creada"


# ----------------------------------------------------------------------
# Dashboards
# ----------------------------------------------------------------------

def configurar_formato_espanol(mb):
    """Números con formato español en toda la instancia: 1.234,56 en vez de 1,234.56."""
    try:
        mb.put("setting/custom-formatting", {"value": {
            "type/Number": {"number_separators": ",."},     # coma decimal, punto de miles
            "type/Currency": {"currency": "EUR"},
        }})
        print("  Formato de números: español (1.234,56)")
    except RuntimeError as error:
        # No es imprescindible: si esta versión de Metabase no lo admite, seguimos
        print(f"  Aviso: no se pudo cambiar el formato de números ({error})")


def crear_dashboard(mb, definicion, id_bd, id_coleccion):
    print(f"\n{definicion['nombre']}")
    id_dashboard = mb.buscar_en_coleccion(id_coleccion, "dashboard", definicion["nombre"])
    if id_dashboard is None:
        id_dashboard = mb.post("dashboard", {"name": definicion["nombre"],
                                             "description": definicion["descripcion"],
                                             "collection_id": id_coleccion})["id"]

    colocadas = []
    for n, tarjeta in enumerate(definicion["tarjetas"], start=1):
        id_tarjeta, accion = crear_o_actualizar_tarjeta(mb, tarjeta, id_bd, id_coleccion)
        fila, columna, ancho, alto = tarjeta["pos"]
        # id negativo = "crea esta tarjeta en el dashboard"
        colocadas.append({"id": -n, "card_id": id_tarjeta,
                          "row": fila, "col": columna, "size_x": ancho, "size_y": alto})
        print(f"  [{accion:<11}] {tarjeta['nombre']}")

    # La lista sustituye TODO lo que hubiera en el dashboard: así queda exactamente como en dashboards.py
    mb.put(f"dashboard/{id_dashboard}", {"dashcards": colocadas,
                                         "description": definicion["descripcion"]})
    print(f"  -> {URL}/dashboard/{id_dashboard}")


def main():
    mb = Metabase(URL)
    try:
        mb.esperar_arranque()
        mb.iniciar_sesion()
        id_bd = conectar_base_de_datos(mb)
        id_coleccion = preparar_coleccion(mb)
        configurar_formato_espanol(mb)
        for definicion in DASHBOARDS:
            crear_dashboard(mb, definicion, id_bd, id_coleccion)
    except RuntimeError as error:
        print(f"\nERROR: {error}")
        sys.exit(1)
    print(f"\nListo. Entra en {URL} con {ADMIN_EMAIL}")


if __name__ == "__main__":
    main()