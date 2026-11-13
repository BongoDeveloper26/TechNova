"""
prevision_ventas.py -> Fase 8b: previsión de las ventas diarias de los próximos 3 meses.

Es aprendizaje SUPERVISADO (regresión): el modelo aprende de los días pasados,
de los que sabemos cuánto se vendió, para estimar los días futuros.

La clave para hacerlo bien es NO hacer trampas con el tiempo:
  - Para prever un día que está a 92 días vista, solo se puede usar información
    que ya se conocía 92 días antes. Por eso el "nivel" de ventas de cada día es
    la media de los 28 días que terminan 92 días antes.
  - Para medir el error se hace un BACKTEST: se esconde el último trimestre, se
    entrena con lo anterior y se compara la previsión con lo que pasó de verdad.

Se comparan 4 modelos en el backtest y se queda el mejor para cada canal:
  1. media_4_semanas     -> la media de los 4 últimos días iguales (lunes con lunes...)
  2. anio_anterior       -> el mismo día del año pasado x el crecimiento de los últimos 3 meses
  3. gradient_boosting   -> HistGradientBoosting (scikit-learn) con variables de calendario
                            (día de la semana, mes, festivos, Black Friday...) sobre el nivel
  4. combinado           -> la media de 2 y 3 (un "ensemble": sus errores se compensan)

Las 2 primeras son "modelos ingenuos": si el modelo de ML no les gana, no sirve de nada.

Validación temporal en 3 tramos (nunca se elige nada mirando el periodo con el que se evalúa):
    |------------- entrenamiento -------------|-- validación --|-- test (backtest) --|
  - En la VALIDACIÓN se elige cuánto peso dar a los días recientes (vida media de los pesos):
    TechNova crece cada vez más despacio, y lo de hace dos años se parece poco a lo de ahora.
  - En el TEST se comparan los 4 modelos y se elige el mejor.

Guarda en el esquema ml: prevision_ventas, backtest_ventas y metricas_prevision.

Uso:
    python ml/prevision_ventas.py
"""
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from comun import (CARPETA_GRAFICOS, CARPETA_MODELOS, COLORES, SEMILLA, a_python, conectar_dw, leer,
                   preparar_esquema, preparar_graficos, registrar_ejecucion)

HORIZONTE = 92             # días que se prevén (unos 3 meses)
VENTANA_NIVEL = 28         # el nivel de ventas es la media de 28 días...
CANALES = ["web", "tienda"]
MODELOS = ["media_4_semanas", "anio_anterior", "gradient_boosting", "combinado"]
VARIABLES = ["dia_semana", "mes", "dia_mes", "festivo", "dias_black_friday", "dias_navidad"]
CONFIANZA = (0.10, 0.90)   # intervalo del 80 %
# Vida media de los pesos (días): un día de hace 90 días pesa la mitad que el más reciente.
# None = todos los días pesan igual. Se elige automáticamente en la validación.
VIDAS_MEDIAS = [None, 365, 180, 90, 45]


# ---------------------------------------------------------------------
# Datos y variables
# ---------------------------------------------------------------------

def extraer_series(conn):
    ventas = leer(conn, """
        SELECT f.fecha, c.canal, COALESCE(SUM(v.importe_neto), 0) AS ventas
        FROM marts.dim_fecha f
        CROSS JOIN (VALUES ('web'), ('tienda')) AS c(canal)
        LEFT JOIN marts.fct_ventas v ON v.dia = f.fecha AND v.canal = c.canal
        WHERE f.fecha BETWEEN (SELECT MIN(dia) FROM marts.fct_ventas) AND (SELECT MAX(dia) FROM marts.fct_ventas)
        GROUP BY f.fecha, c.canal
        ORDER BY f.fecha
    """, fechas=("fecha",))
    festivos = set(leer(conn, "SELECT fecha FROM seeds.festivos_nacionales", fechas=("fecha",)).fecha)
    series = {canal: ventas[ventas.canal == canal].set_index("fecha").ventas.asfreq("D", fill_value=0)
              for canal in CANALES}
    return series, festivos


def black_friday(anio: int) -> pd.Timestamp:
    """El último viernes de noviembre."""
    dia = pd.Timestamp(anio, 11, 30)
    return dia - pd.Timedelta(days=(dia.weekday() - 4) % 7)


def calendario(fechas: pd.DatetimeIndex, festivos) -> pd.DataFrame:
    X = pd.DataFrame(index=fechas)
    X["dia_semana"] = fechas.day_of_week
    X["mes"] = fechas.month
    X["dia_mes"] = fechas.day
    X["festivo"] = fechas.isin(festivos).astype(int)
    bf = pd.DatetimeIndex([black_friday(a) for a in fechas.year])
    X["dias_black_friday"] = np.clip((fechas - bf).days, -30, 30)       # -30 = un mes antes, +30 = un mes después
    navidad = pd.to_datetime([f"{a}-12-25" for a in fechas.year])
    X["dias_navidad"] = np.clip((navidad - fechas).days, -10, 40)
    return X


def nivel(serie: pd.Series, fechas: pd.DatetimeIndex) -> pd.Series:
    """Media de los 28 días que terminan HORIZONTE días antes de cada fecha (lo que se sabía entonces)."""
    media = serie.rolling(VENTANA_NIVEL).mean()
    return pd.Series(media.reindex(fechas - pd.Timedelta(days=HORIZONTE)).values, index=fechas)


# ---------------------------------------------------------------------
# Los 3 modelos: todos reciben la historia hasta un corte y prevén las fechas pedidas
# ---------------------------------------------------------------------

def prever_media_4_semanas(historia: pd.Series, fechas: pd.DatetimeIndex) -> pd.Series:
    ultimas = historia.iloc[-28:]
    medias = ultimas.groupby(ultimas.index.day_of_week).mean()
    return pd.Series(medias.reindex(fechas.day_of_week).values, index=fechas)


def prever_anio_anterior(historia: pd.Series, fechas: pd.DatetimeIndex) -> pd.Series:
    corte = historia.index.max()
    reciente = historia[historia.index > corte - pd.Timedelta(days=90)].sum()
    hace_un_anio = historia[(historia.index > corte - pd.Timedelta(days=90 + 364))
                            & (historia.index <= corte - pd.Timedelta(days=364))].sum()
    crecimiento = reciente / hace_un_anio if hace_un_anio else 1.0
    # 364 días = 52 semanas exactas: se compara lunes con lunes
    anterior = historia.reindex(fechas - pd.Timedelta(days=364)).fillna(0).values
    return pd.Series(anterior * crecimiento, index=fechas)


def pesos(fechas: pd.DatetimeIndex, vida_media):
    """Los días recientes pesan más: el peso se reduce a la mitad cada `vida_media` días."""
    if vida_media is None:
        return None
    edad = (fechas.max() - fechas).days.values
    return 0.5 ** (edad / vida_media)


def entrenar_gradient_boosting(historia: pd.Series, festivos, vida_media=None):
    """
    El modelo aprende el COCIENTE ventas del día / nivel: así no le afecta que la empresa
    crezca (los árboles de decisión no saben extrapolar una tendencia) y solo tiene que
    aprender la forma: qué días se vende más o menos que lo normal.
    """
    fechas = historia.index
    base = nivel(historia, fechas)
    validos = base.notna() & (base > 0)
    X = calendario(fechas, festivos)[validos]
    y = (historia / base)[validos]
    modelo = HistGradientBoostingRegressor(max_iter=400, learning_rate=0.04, max_leaf_nodes=15,
                                           min_samples_leaf=20, random_state=SEMILLA)
    return modelo.fit(X, y, sample_weight=pesos(X.index, vida_media))


def elegir_vida_media(historia: pd.Series, festivos):
    """Separa los últimos HORIZONTE días de la historia como validación y prueba cada vida media."""
    corte = historia.index.max() - pd.Timedelta(days=HORIZONTE)
    entrenamiento, validacion = historia[historia.index <= corte], historia[historia.index > corte]
    errores = {}
    for vida in VIDAS_MEDIAS:
        modelo = entrenar_gradient_boosting(entrenamiento, festivos, vida)
        prevision = prever_gradient_boosting(entrenamiento, validacion.index, festivos, modelo)
        errores[vida] = metricas(validacion, prevision)["wape"]
    return min(errores, key=errores.get), errores


def prever_gradient_boosting(historia: pd.Series, fechas: pd.DatetimeIndex, festivos, modelo=None):
    modelo = modelo or entrenar_gradient_boosting(historia, festivos)
    base = nivel(historia, fechas)
    return pd.Series(np.clip(modelo.predict(calendario(fechas, festivos)), 0, None) * base.values, index=fechas)


def prever(nombre, historia, fechas, festivos, modelo_gb=None):
    if nombre == "media_4_semanas":
        return prever_media_4_semanas(historia, fechas)
    if nombre == "anio_anterior":
        return prever_anio_anterior(historia, fechas)
    if nombre == "gradient_boosting":
        return prever_gradient_boosting(historia, fechas, festivos, modelo_gb)
    return (prever_anio_anterior(historia, fechas)
            + prever_gradient_boosting(historia, fechas, festivos, modelo_gb)) / 2


# ---------------------------------------------------------------------
# Backtest y métricas
# ---------------------------------------------------------------------

def metricas(real: pd.Series, prevision: pd.Series) -> dict:
    mensual_real = real.resample("MS").sum()
    mensual_prev = prevision.resample("MS").sum()
    return {
        "wape": float((real - prevision).abs().sum() / real.sum()),
        "error_mensual": float(((mensual_prev - mensual_real).abs() / mensual_real).mean()),
        "sesgo": float(prevision.sum() / real.sum() - 1),
    }


def backtest(serie: pd.Series, festivos):
    """Esconde los últimos HORIZONTE días, prevé con los 4 modelos y compara con lo real."""
    corte = serie.index.max() - pd.Timedelta(days=HORIZONTE)
    historia, real = serie[serie.index <= corte], serie[serie.index > corte]
    vida_media, _errores = elegir_vida_media(historia, festivos)        # solo con la historia
    modelo_gb = entrenar_gradient_boosting(historia, festivos, vida_media)   # lo usan 2 modelos
    previsiones = {m: prever(m, historia, real.index, festivos, modelo_gb) for m in MODELOS}
    resultados = {m: metricas(real, p) for m, p in previsiones.items()}
    return real, previsiones, resultados


# ---------------------------------------------------------------------
# Gráficos
# ---------------------------------------------------------------------

def graficos(series, backtests, futuras, elegidos):
    plt = preparar_graficos()

    # Backtest: lo real frente a lo que habría dicho cada modelo (semanal, para que se lea bien)
    fig, ejes = plt.subplots(1, len(CANALES), figsize=(12, 4), sharey=False)
    for ax, canal in zip(ejes, CANALES):
        real, previsiones, resultados = backtests[canal]
        ax.plot(real.resample("W").sum(), color="black", lw=2.2, label="Real")
        for i, m in enumerate(MODELOS):
            ax.plot(previsiones[m].resample("W").sum(), color=COLORES[i], lw=1.6,
                    ls="-" if m == elegidos[canal] else "--",
                    label=f"{m} (WAPE {resultados[m]['wape']:.0%})")
        ax.set(title=f"Backtest {canal}: último trimestre", ylabel="Ventas por semana (€)")
        ax.yaxis.set_major_formatter(lambda v, _: f"{v / 1000:,.0f} k")
        ax.legend(frameon=False, fontsize=7.5)
        ax.tick_params(axis="x", rotation=30)
    fig.savefig(CARPETA_GRAFICOS / "05_backtest_modelos.png")
    plt.close(fig)

    # Previsión mensual: los últimos 12 meses reales y los próximos 3 previstos
    fig, ejes = plt.subplots(1, len(CANALES), figsize=(12, 4))
    for ax, canal in zip(ejes, CANALES):
        real = series[canal]
        real = real[real.index > real.index.max() - pd.DateOffset(months=12)].resample("MS").sum()
        futura = futuras[canal].set_index("fecha").prevision.resample("MS").sum()
        ax.bar(real.index, real.values, width=20, color=COLORES[0], alpha=0.85, label="Real")
        ax.bar(futura.index, futura.values, width=20, color=COLORES[1], alpha=0.9,
               label=f"Previsión ({elegidos[canal]})")
        ax.set(title=f"Ventas {canal}: últimos 12 meses y próximos 3", ylabel="Ventas por mes (€)")
        ax.yaxis.set_major_formatter(lambda v, _: f"{v / 1000:,.0f} k")
        ax.legend(frameon=False, fontsize=8)
        ax.tick_params(axis="x", rotation=30)
    fig.savefig(CARPETA_GRAFICOS / "06_prevision_mensual.png")
    plt.close(fig)

    # Previsión diaria con su intervalo del 80 %
    fig, ejes = plt.subplots(len(CANALES), 1, figsize=(12, 6.5), sharex=True)
    for ax, canal in zip(ejes, CANALES):
        real = series[canal]
        real = real[real.index > real.index.max() - pd.Timedelta(days=60)]
        futura = futuras[canal].set_index("fecha")
        ax.plot(real.index, real.values, color=COLORES[0], lw=1.2, label="Real (últimos 60 días)")
        ax.plot(futura.index, futura.prevision, color=COLORES[1], lw=1.4, label="Previsión")
        ax.fill_between(futura.index, futura.limite_inferior, futura.limite_superior, color=COLORES[1],
                        alpha=0.18, label="Intervalo del 80 %")
        ax.set(title=f"Ventas diarias {canal}", ylabel="€ por día")
        ax.legend(frameon=False, fontsize=8, loc="upper left")
    fig.savefig(CARPETA_GRAFICOS / "07_prevision_diaria.png")
    plt.close(fig)


# ---------------------------------------------------------------------
# Proceso completo
# ---------------------------------------------------------------------

def guardar(conn, backtests, metricas_df, futuras, id_ejecucion):
    conn.execute("TRUNCATE ml.prevision_ventas, ml.backtest_ventas, ml.metricas_prevision")
    with conn.cursor() as cur:
        filas = []
        for canal, (real, previsiones, _r) in backtests.items():
            for fecha in real.index:
                filas.append((fecha.date(), canal, round(float(real[fecha]), 2),
                              *[round(float(previsiones[m][fecha]), 2) for m in MODELOS]))
        cur.executemany("""INSERT INTO ml.backtest_ventas
                           (fecha, canal, real, media_4_semanas, anio_anterior, gradient_boosting, combinado)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)""", filas)
        cur.executemany("""INSERT INTO ml.metricas_prevision
                           (canal, modelo, wape, error_mensual, sesgo, elegido, id_ejecucion)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                        [tuple(a_python(v) for v in f) + (id_ejecucion,)
                         for f in metricas_df.round(4).itertuples(index=False)])
        for canal, futura in futuras.items():
            cur.executemany("""INSERT INTO ml.prevision_ventas
                               (fecha, canal, modelo, prevision, limite_inferior, limite_superior, id_ejecucion)
                               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                            [(f.fecha.date(), canal, f.modelo, round(f.prevision, 2), round(f.limite_inferior, 2),
                              round(f.limite_superior, 2), id_ejecucion) for f in futura.itertuples()])


def entrenar(conn, con_graficos=True) -> dict:
    preparar_esquema(conn)
    series, festivos = extraer_series(conn)
    dias = len(series[CANALES[0]])
    if dias < 365 + 2 * HORIZONTE:
        raise RuntimeError(f"Solo hay {dias} días de ventas: hacen falta al menos {365 + 2 * HORIZONTE}")
    with registrar_ejecucion(conn, "prevision_ventas",
                             {"horizonte_dias": HORIZONTE, "ventana_nivel": VENTANA_NIVEL, "modelos": MODELOS, "vidas_medias": VIDAS_MEDIAS,
                              "variables": VARIABLES, "confianza": CONFIANZA, "semilla": SEMILLA}) as ejecucion:
        backtests, filas_metricas, futuras, elegidos, vidas = {}, [], {}, {}, {}
        for canal in CANALES:
            serie = series[canal]
            real, previsiones, resultados = backtest(serie, festivos)
            backtests[canal] = (real, previsiones, resultados)
            # El mejor modelo es el de menor error diario (WAPE) en el backtest
            elegido = min(resultados, key=lambda m: resultados[m]["wape"])
            elegidos[canal] = elegido
            filas_metricas += [(canal, m, r["wape"], r["error_mensual"], r["sesgo"], m == elegido)
                               for m, r in resultados.items()]

            # Intervalo: cuánto se equivocó el modelo elegido en el backtest (cocientes real / previsto)
            cocientes = (real / previsiones[elegido].replace(0, np.nan)).dropna()
            bajo, alto = np.quantile(cocientes, CONFIANZA)

            # Previsión de verdad: se entrena con TODA la historia y se prevén los próximos días
            # Hasta el final del tercer mes completo (como mucho HORIZONTE días: lo que permite el "nivel")
            inicio = serie.index.max() + pd.Timedelta(days=1)
            fin = min(inicio + pd.DateOffset(months=3) - pd.Timedelta(days=1),
                      inicio + pd.Timedelta(days=HORIZONTE - 1))
            futuro = pd.date_range(inicio, fin, freq="D")
            # La vida media se vuelve a elegir con los datos más recientes (validación = último trimestre)
            vida_media, errores_validacion = elegir_vida_media(serie, festivos)
            vidas[canal] = {"elegida": vida_media,
                            "wape_por_vida_media": {str(v): round(e, 4) for v, e in errores_validacion.items()}}
            modelo_gb = entrenar_gradient_boosting(serie, festivos, vida_media)
            CARPETA_MODELOS.mkdir(parents=True, exist_ok=True)
            joblib.dump({"modelo": modelo_gb, "variables": VARIABLES, "horizonte": HORIZONTE,
                         "ventana_nivel": VENTANA_NIVEL, "vida_media": vida_media},
                        CARPETA_MODELOS / f"prevision_{canal}.joblib")
            prevision = prever(elegido, serie, futuro, festivos, modelo_gb)
            futuras[canal] = pd.DataFrame({"fecha": futuro, "modelo": elegido, "prevision": prevision.values,
                                           "limite_inferior": prevision.values * bajo,
                                           "limite_superior": prevision.values * alto})

        metricas_df = pd.DataFrame(filas_metricas, columns=["canal", "modelo", "wape", "error_mensual",
                                                            "sesgo", "elegido"])
        guardar(conn, backtests, metricas_df, futuras, ejecucion["id"])
        if con_graficos:
            graficos(series, backtests, futuras, elegidos)

        ejecucion["datos_hasta"] = series[CANALES[0]].index.max().date()
        ejecucion["metricas"] = {
            "elegidos": elegidos,
            "vida_media_pesos": vidas,
            "backtest": metricas_df.round(4).to_dict("records"),
            "prevision_total": {c: round(float(f.prevision.sum()), 2) for c, f in futuras.items()},
        }
        return {"elegidos": elegidos, "metricas": metricas_df, "futuras": futuras, "vidas": vidas}


def ejecutar(log=print) -> dict:
    inicio = time.time()
    with conectar_dw() as conn:
        r = entrenar(conn)
    log(f"Previsión de ventas a {HORIZONTE} días en {time.time() - inicio:.1f} s. Backtest del último trimestre:")
    for f in r["metricas"].itertuples():
        marca = "  <- elegido" if f.elegido else ""
        log(f"   {f.canal:<7} {f.modelo:<18} WAPE {f.wape:6.1%}   error mensual {f.error_mensual:6.1%}   "
            f"sesgo {f.sesgo:+6.1%}{marca}")
    for canal, v in r["vidas"].items():
        log(f"   Vida media de los pesos ({canal}): {v['elegida'] or 'sin pesos'} días")
    for canal, futura in r["futuras"].items():
        mensual = futura.set_index("fecha").prevision.resample("MS").sum()
        log(f"   Previsión {canal}: " + " | ".join(f"{m:%Y-%m} {v:,.0f} €" for m, v in mensual.items()))
    return {"elegidos": r["elegidos"],
            "prevision_total": {c: round(float(f.prevision.sum()), 2) for c, f in r["futuras"].items()}}


if __name__ == "__main__":
    ejecutar()