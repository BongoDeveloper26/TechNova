"""
segmentacion_clientes.py -> Fase 8a: segmentación de clientes con K-Means.

La segmentación RFM de dbt (int_clientes_rfm) usa REGLAS escritas a mano
("si R >= 4 y F >= 4 y M >= 4 -> Campeones"). Aquí es al revés: le damos al
algoritmo varias características de cada cliente y él solo encuentra los
grupos de clientes parecidos entre sí (aprendizaje NO supervisado).

Pasos:
  1. Variables de cada cliente (desde marts.fct_ventas):
       recencia, pedidos, gasto neto, ticket medio, % de pedidos en la web y tasa de devolución
  2. Preparación: logaritmo en las variables muy asimétricas y estandarización
     (K-Means mide distancias: sin escalar, el gasto en euros aplastaría al resto)
  3. Elegir k (nº de grupos): método del codo + coeficiente de silueta
  4. Entrenar K-Means y poner NOMBRE a cada grupo según su perfil (centroide)
  5. Guardar: ml.segmento_cliente, ml.segmento_resumen, el modelo (.joblib) y los gráficos

Uso:
    python ml/segmentacion_clientes.py
"""
import re
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.compose import ColumnTransformer
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, StandardScaler

from comun import (CARPETA_GRAFICOS, CARPETA_MODELOS, COLORES, SEMILLA, a_python, conectar_dw, leer,
                   preparar_esquema, preparar_graficos, registrar_ejecucion)

VARIABLES = ["recencia_dias", "pedidos", "gasto_neto", "ticket_medio", "pct_web", "tasa_devolucion"]
VARIABLES_LOG = ["recencia_dias", "pedidos", "gasto_neto", "ticket_medio"]   # muy asimétricas
NOMBRES_VARIABLES = {"recencia_dias": "Días sin comprar", "pedidos": "Pedidos", "gasto_neto": "Gasto neto",
                     "ticket_medio": "Ticket medio", "pct_web": "% pedidos web",
                     "tasa_devolucion": "Tasa de devolución"}
K_PROBADOS = range(2, 10)
K_CANDIDATOS = range(4, 7)   # menos de 4 grupos es poco útil para marketing; más de 6, difícil de manejar

# Qué significa cada segmento y qué haría el equipo de marketing con él
SEGMENTOS = {
    "VIP": ("Compran a menudo, gastan mucho y han comprado hace poco.",
            "Programa de fidelización, acceso anticipado a lanzamientos y atención preferente."),
    "Devuelven mucho": ("Una parte importante de lo que compran acaba devuelto.",
                        "Revisar motivos de devolución y mejorar fichas de producto y tallas/especificaciones."),
    "Valiosos dormidos": ("Gastaron bastante, pero hace tiempo que no compran.",
                          "Campaña de reactivación personalizada con un incentivo fuerte."),
    "Dormidos": ("Hace mucho que no compran y su gasto fue bajo.",
                 "Recordatorio por email de bajo coste; no invertir mucho en ellos."),
    "Alto ticket ocasional": ("Compran poco, pero cada compra es cara.",
                              "Venta cruzada de accesorios y garantías, financiación y avisos de novedades premium."),
    "De tienda ocasionales": ("Compran casi siempre en tienda física, pocas veces y por poco importe.",
                              "Atraerlos a la web (cupón de primera compra online) y a eventos en tienda."),
    "Fieles a la tienda": ("Compran sobre todo en tienda física y con buen gasto.",
                           "Atención personal del vendedor y ofertas exclusivas en tienda."),
    "Digitales de bajo gasto": ("Compran casi solo en la web, con pedidos pequeños.",
                                "Subir el ticket: packs, envío gratis a partir de un importe y recomendaciones."),
    "Digitales": ("Compran sobre todo en la web con un gasto normal.",
                  "Newsletter personalizada y recomendaciones según lo que han comprado."),
    "Nuevos": ("Han comprado hace poco y todavía pocas veces.",
               "Secuencia de bienvenida para conseguir la segunda compra."),
    "Habituales": ("Clientes de perfil medio en todas las variables.",
                   "Campañas generales de temporada."),
}


# ---------------------------------------------------------------------
# 1. Datos
# ---------------------------------------------------------------------

def extraer_variables(conn) -> pd.DataFrame:
    return leer(conn, """
        WITH referencia AS (SELECT MAX(dia) AS hoy FROM marts.fct_ventas)
        SELECT v.id_cliente,
               r.hoy - MAX(v.dia)                                          AS recencia_dias,
               COUNT(DISTINCT v.id_pedido)                                 AS pedidos,
               SUM(v.importe_neto - v.importe_devuelto)                    AS gasto_neto,
               SUM(v.importe_neto) / COUNT(DISTINCT v.id_pedido)           AS ticket_medio,
               COUNT(DISTINCT v.id_pedido) FILTER (WHERE v.canal = 'web')::numeric
                   / COUNT(DISTINCT v.id_pedido)                           AS pct_web,
               COALESCE(SUM(v.importe_devuelto) / NULLIF(SUM(v.importe_neto), 0), 0) AS tasa_devolucion,
               COUNT(DISTINCT p.categoria)                                 AS categorias,
               MAX(c.segmento_rfm)                                         AS segmento_rfm,
               r.hoy                                                       AS datos_hasta
        FROM marts.fct_ventas v
        JOIN marts.dim_producto p USING (id_producto)
        JOIN marts.dim_cliente c USING (id_cliente)
        CROSS JOIN referencia r
        WHERE v.id_cliente IS NOT NULL
        GROUP BY v.id_cliente, r.hoy
        HAVING SUM(v.importe_neto) > 0
    """)


# ---------------------------------------------------------------------
# 2-3. Preparación y elección de k
# ---------------------------------------------------------------------

def preparacion() -> Pipeline:
    """log(1 + x) en las variables asimétricas y después todo a media 0 y desviación 1."""
    # VARIABLES empieza por las de VARIABLES_LOG: el orden de las columnas no cambia
    log = ColumnTransformer([("log", FunctionTransformer(np.log1p), VARIABLES_LOG)], remainder="passthrough")
    return Pipeline([("log", log), ("escala", StandardScaler())])


def elegir_k(X: np.ndarray):
    """Entrena K-Means con varios k y mide la inercia (codo) y la silueta de cada uno."""
    pruebas = []
    muestra = min(len(X), 4000)   # la silueta es lenta: se calcula sobre una muestra
    for k in K_PROBADOS:
        km = KMeans(n_clusters=k, n_init=10, random_state=SEMILLA).fit(X)
        silueta = silhouette_score(X, km.labels_, sample_size=muestra, random_state=SEMILLA)
        pruebas.append({"k": k, "inercia": km.inertia_, "silueta": silueta})
    pruebas = pd.DataFrame(pruebas)
    candidatos = pruebas[pruebas.k.isin(K_CANDIDATOS)]
    k = int(candidatos.loc[candidatos.silueta.idxmax(), "k"])
    return k, pruebas


# ---------------------------------------------------------------------
# 4. Nombres de los segmentos
# ---------------------------------------------------------------------

def nombre_segmento(z: pd.Series) -> str:
    """
    z = el centroide del grupo en unidades estandarizadas (0 = como el cliente medio,
    +1 = una desviación típica por encima). Las reglas miran lo que más destaca del grupo.
    """
    if z.tasa_devolucion > 1.5:
        return "Devuelven mucho"
    if z.gasto_neto > 0.7 and z.pedidos > 0.7:
        return "VIP"
    if z.recencia_dias > 0.8:
        return "Valiosos dormidos" if z.gasto_neto > 0.3 else "Dormidos"
    if z.ticket_medio > 0.5 and z.pedidos < 0.3:
        return "Alto ticket ocasional"
    if z.pct_web < -0.8:
        return "De tienda ocasionales" if z.gasto_neto < 0 else "Fieles a la tienda"
    if z.pct_web > 0.6:
        return "Digitales de bajo gasto" if z.gasto_neto < 0 else "Digitales"
    if z.recencia_dias < -0.5 and z.pedidos < 0:
        return "Nuevos"
    return "Habituales"


# Si dos grupos reciben el mismo nombre, el segundo se distingue por la variable en la que más se
# diferencian: (variable, adjetivo si está por encima, adjetivo si está por debajo)
MATICES = [("recencia_dias", "inactivos", "recientes"), ("pct_web", "online", "en tienda"),
           ("gasto_neto", "de mayor gasto", "de menor gasto"), ("ticket_medio", "de ticket alto", "de ticket bajo"),
           ("pedidos", "más frecuentes", "menos frecuentes")]


def nombre_base(nombre: str) -> str:
    """'Alto ticket ocasional (recientes)' -> 'Alto ticket ocasional'."""
    return re.sub(r"( \(.*\))?( bis)*$", "", nombre)


def nombrar(centroides_z: pd.DataFrame) -> dict:
    """{cluster: nombre}, sin repetir nombres."""
    nombres, primero = {}, {}
    # Primero los grupos más "extremos": así se quedan con el nombre más claro
    orden = centroides_z.abs().max(axis=1).sort_values(ascending=False).index
    for cluster in orden:
        z = centroides_z.loc[cluster]
        nombre = nombre_segmento(z)
        if nombre not in primero:
            primero[nombre] = cluster
        else:
            diferencia = z - centroides_z.loc[primero[nombre]]
            variable, alto, bajo = max(MATICES, key=lambda m: abs(diferencia[m[0]]))
            nombre = f"{nombre} ({alto if diferencia[variable] > 0 else bajo})"
            while nombre in nombres.values():
                nombre += " bis"
        nombres[cluster] = nombre
    return nombres


# ---------------------------------------------------------------------
# 5. Gráficos
# ---------------------------------------------------------------------

def graficos(df, X, pruebas, k, nombres, centroides_z):
    plt = preparar_graficos()
    orden = df.groupby("segmento").gasto_neto.sum().sort_values(ascending=False).index
    color = {s: COLORES[i % len(COLORES)] for i, s in enumerate(orden)}

    # Elección de k: codo y silueta
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 3.8))
    a1.plot(pruebas.k, pruebas.inercia, "o-", color=COLORES[0])
    a1.set(title="Método del codo", xlabel="Número de grupos (k)", ylabel="Inercia")
    a2.plot(pruebas.k, pruebas.silueta, "o-", color=COLORES[1])
    a2.axvspan(min(K_CANDIDATOS) - 0.5, max(K_CANDIDATOS) + 0.5, color="#D9E1F2", alpha=0.6, zorder=0,
               label="k útiles para negocio")
    a2.axvline(k, color=COLORES[0], ls="--", label=f"k elegido = {k}")
    a2.set(title="Coeficiente de silueta (más alto = grupos más separados)", xlabel="Número de grupos (k)",
           ylabel="Silueta")
    a2.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=2)
    for a in (a1, a2):
        a.set_xticks(list(pruebas.k))
    fig.savefig(CARPETA_GRAFICOS / "01_eleccion_k.png")
    plt.close(fig)

    # Mapa de clientes en 2D (PCA reduce las 6 variables a 2 para poder dibujarlas)
    pca = PCA(n_components=2, random_state=SEMILLA)
    puntos = pca.fit_transform(X)
    fig, ax = plt.subplots(figsize=(8.5, 5.5))
    for s in orden:
        m = (df.segmento == s).values
        ax.scatter(puntos[m, 0], puntos[m, 1], s=7, alpha=0.55, color=color[s], label=f"{s} ({m.sum():,})")
    ax.set(title="Clientes agrupados por K-Means (proyección PCA en 2 dimensiones)",
           xlabel=f"Componente 1 ({pca.explained_variance_ratio_[0]:.0%} de la variación)",
           ylabel=f"Componente 2 ({pca.explained_variance_ratio_[1]:.0%})")
    ax.legend(frameon=False, markerscale=2.5, fontsize=8, loc="best")
    fig.savefig(CARPETA_GRAFICOS / "02_mapa_segmentos.png")
    plt.close(fig)

    # Perfil de cada segmento: mapa de calor con el centroide estandarizado
    perfil = centroides_z.rename(index=nombres).loc[orden].rename(columns=NOMBRES_VARIABLES)
    fig, ax = plt.subplots(figsize=(9, 0.55 * len(perfil) + 1.6))
    im = ax.imshow(perfil.values, cmap="RdBu_r", vmin=-2, vmax=2, aspect="auto")
    ax.set_xticks(range(len(perfil.columns)), perfil.columns, rotation=20, ha="right")
    ax.set_yticks(range(len(perfil)), perfil.index)
    ax.grid(False)
    for i in range(perfil.shape[0]):
        for j in range(perfil.shape[1]):
            ax.text(j, i, f"{perfil.values[i, j]:+.1f}", ha="center", va="center", fontsize=8,
                    color="white" if abs(perfil.values[i, j]) > 1.2 else "black")
    ax.set_title("Perfil de cada segmento (desviaciones respecto al cliente medio)")
    fig.colorbar(im, ax=ax, shrink=0.8, label="rojo = por encima, azul = por debajo")
    fig.savefig(CARPETA_GRAFICOS / "03_perfil_segmentos.png")
    plt.close(fig)

    # Segmentos de K-Means frente a los segmentos por reglas (RFM de dbt)
    cruce = pd.crosstab(df.segmento, df.segmento_rfm).loc[orden]
    fig, ax = plt.subplots(figsize=(9, 0.55 * len(cruce) + 1.6))
    ax.imshow(cruce.values, cmap="Blues", aspect="auto")
    ax.set_xticks(range(len(cruce.columns)), cruce.columns, rotation=20, ha="right")
    ax.set_yticks(range(len(cruce)), cruce.index)
    ax.grid(False)
    for i in range(cruce.shape[0]):
        for j in range(cruce.shape[1]):
            ax.text(j, i, f"{cruce.values[i, j]:,}", ha="center", va="center", fontsize=8,
                    color="white" if cruce.values[i, j] > cruce.values.max() * 0.6 else "black")
    ax.set(title="K-Means (filas) frente a segmentos RFM por reglas (columnas)", xlabel="Segmento RFM (dbt)")
    fig.savefig(CARPETA_GRAFICOS / "04_kmeans_vs_rfm.png")
    plt.close(fig)


# ---------------------------------------------------------------------
# Proceso completo
# ---------------------------------------------------------------------

def guardar(conn, df, resumen, id_ejecucion):
    conn.execute("TRUNCATE ml.segmento_cliente, ml.segmento_resumen")
    with conn.cursor() as cur:
        cur.executemany("""
            INSERT INTO ml.segmento_cliente (id_cliente, cluster, segmento, recencia_dias, pedidos, gasto_neto,
                   ticket_medio, pct_web, tasa_devolucion, categorias, segmento_rfm, id_ejecucion)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, [tuple(a_python(v) for v in fila) + (id_ejecucion,) for fila in df[
            ["id_cliente", "cluster", "segmento", "recencia_dias", "pedidos", "gasto_neto", "ticket_medio",
             "pct_web", "tasa_devolucion", "categorias", "segmento_rfm"]].itertuples(index=False)])
        cur.executemany("""
            INSERT INTO ml.segmento_resumen (segmento, cluster, clientes, pct_clientes, gasto_total, pct_gasto,
                   recencia_media, pedidos_medio, gasto_medio, ticket_medio, pct_web, tasa_devolucion,
                   descripcion, accion, id_ejecucion)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, [tuple(a_python(v) for v in fila) + (id_ejecucion,) for fila in resumen.itertuples(index=False)])


def entrenar(conn, con_graficos=True) -> dict:
    preparar_esquema(conn)
    df = extraer_variables(conn)
    if len(df) < 100:
        raise RuntimeError(f"Solo hay {len(df)} clientes con compras: muy pocos para segmentar")
    with registrar_ejecucion(conn, "segmentacion_clientes",
                             {"variables": VARIABLES, "variables_log": VARIABLES_LOG,
                              "k_probados": list(K_PROBADOS), "k_candidatos": list(K_CANDIDATOS),
                              "semilla": SEMILLA}) as ejecucion:
        prep = preparacion()
        X = prep.fit_transform(df[VARIABLES])
        k, pruebas = elegir_k(X)

        modelo = KMeans(n_clusters=k, n_init=20, random_state=SEMILLA).fit(X)
        df["cluster"] = modelo.labels_
        centroides_z = pd.DataFrame(modelo.cluster_centers_, columns=VARIABLES)
        nombres = nombrar(centroides_z)
        df["segmento"] = df.cluster.map(nombres)

        # Resumen por segmento, con su descripción y la acción recomendada
        g = df.groupby("segmento")
        resumen = pd.DataFrame({
            "cluster": g.cluster.first(), "clientes": g.size(),
            "pct_clientes": g.size() / len(df), "gasto_total": g.gasto_neto.sum().round(2),
            "pct_gasto": g.gasto_neto.sum() / df.gasto_neto.sum(),
            "recencia_media": g.recencia_dias.mean().round(1), "pedidos_medio": g.pedidos.mean().round(2),
            "gasto_medio": g.gasto_neto.mean().round(2), "ticket_medio": g.ticket_medio.mean().round(2),
            "pct_web": g.pct_web.mean().round(4), "tasa_devolucion": g.tasa_devolucion.mean().round(4),
        }).sort_values("gasto_total", ascending=False)
        base = [nombre_base(n) for n in resumen.index]
        resumen["descripcion"] = [SEGMENTOS[b][0] for b in base]
        resumen["accion"] = [SEGMENTOS[b][1] for b in base]
        resumen = resumen.reset_index()

        guardar(conn, df, resumen, ejecucion["id"])
        CARPETA_MODELOS.mkdir(parents=True, exist_ok=True)
        joblib.dump({"preparacion": prep, "kmeans": modelo, "nombres": nombres, "variables": VARIABLES},
                    CARPETA_MODELOS / "segmentacion_kmeans.joblib")
        if con_graficos:
            graficos(df, X, pruebas, k, nombres, centroides_z)

        silueta = float(pruebas.loc[pruebas.k == k, "silueta"].iloc[0])
        ejecucion["datos_hasta"] = df.datos_hasta.max()
        ejecucion["metricas"] = {
            "clientes": len(df), "k": k, "silueta": round(silueta, 4),
            "inercia": round(float(modelo.inertia_), 1),
            "pruebas": pruebas.round(4).to_dict("records"),
            "segmentos": dict(zip(resumen.segmento, resumen.clientes.astype(int))),
        }
        return {"clientes": len(df), "k": k, "silueta": silueta, "resumen": resumen}


def ejecutar(log=print) -> dict:
    inicio = time.time()
    with conectar_dw() as conn:
        r = entrenar(conn)
    log(f"Segmentación: {r['clientes']:,} clientes en {r['k']} segmentos "
        f"(silueta {r['silueta']:.3f}) en {time.time() - inicio:.1f} s")
    for fila in r["resumen"].itertuples():
        log(f"   {fila.segmento:<26} {fila.clientes:>6,} clientes ({fila.pct_clientes:5.1%})   "
            f"{fila.pct_gasto:5.1%} del gasto")
    return {"clientes": r["clientes"], "k": r["k"], "silueta": round(r["silueta"], 4)}


if __name__ == "__main__":
    ejecutar()