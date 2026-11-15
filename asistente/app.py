"""
app.py -> Interfaz web del asistente (chat) con Streamlit.

    streamlit run asistente/app.py          ->  http://localhost:8501

Cada respuesta muestra el resumen en lenguaje natural, un gráfico (el tipo lo elige el LLM),
y dos desplegables para ver el SQL generado y la tabla de datos (descargable en CSV).
Recuerda la conversación: se puede preguntar "¿y en 2024?" después de otra pregunta.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import altair as alt  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import bd  # noqa: E402
import llm  # noqa: E402
from asistente import preguntar  # noqa: E402
from esquema import contexto  # noqa: E402

EJEMPLOS = [
    "¿Qué tienda vendió más en noviembre de 2025?",
    "¿Cómo evolucionó la facturación mensual en 2025 por canal?",
    "Top 10 productos por margen en 2025",
    "¿Qué método de pago se usa más en la web?",
    "¿Qué centro tuvo más absentismo en 2025?",
    "¿Cuánto gasta de media cada segmento de clientes?",
    "¿Qué transportista tarda más en entregar?",
    "¿Cuántas ventas se esperan en enero de 2026?",
]
COLOR = "#2F5597"

st.set_page_config(page_title="TechNova · Asistente de datos", layout="wide")


@st.cache_resource(show_spinner="Preparando la conexión con el data warehouse...")
def preparar():
    tablas = bd.preparar()
    contexto()   # se calcula una vez y se queda en memoria
    return tablas


def estadisticas():
    try:
        with bd.conectar_dw() as conn:
            return conn.execute("""
                SELECT COUNT(*), AVG(correcta::int), AVG(segundos) FROM asistente.consulta
            """).fetchone()
    except Exception:
        return None


def grafico(df: pd.DataFrame, tipo: str):
    """Gráfico con la primera columna de texto/fecha como eje y las numéricas como valores."""
    if tipo == "ninguno" or df.empty or len(df) < 2:
        return None
    numericas = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    categorias = [c for c in df.columns if c not in numericas]
    if not numericas or not categorias:
        return None
    x, y = categorias[0], numericas[0]
    df = df.copy()
    df[x] = df[x].astype(str)
    if tipo == "lineas":
        otras = categorias[1:2]   # p. ej. mes + canal: una línea por canal
        base = alt.Chart(df).mark_line(point=True, strokeWidth=2.5).encode(
            x=alt.X(x, title=None, sort=None), y=alt.Y(y, title=y.replace("_", " ")),
            tooltip=list(df.columns))
        if otras:
            return base.encode(color=alt.Color(otras[0], title=None, scale=alt.Scale(scheme="tableau10")))
        return base.encode(color=alt.value(COLOR))
    if tipo == "tarta":
        return alt.Chart(df).mark_arc(innerRadius=60).encode(
            theta=alt.Theta(y), color=alt.Color(x, title=None, scale=alt.Scale(scheme="tableau10")),
            tooltip=list(df.columns))
    return alt.Chart(df.head(25)).mark_bar(color=COLOR, cornerRadiusEnd=3).encode(
        y=alt.Y(x, title=None, sort="-x"), x=alt.X(y, title=y.replace("_", " ")), tooltip=list(df.columns))


def mostrar(r):
    if r.error:
        st.error(r.texto)
        with st.expander("Detalle del error"):
            st.code(r.error)
    else:
        st.markdown(r.texto)
    if r.filas:
        df = pd.DataFrame(r.filas, columns=r.columnas)
        for c in df.columns:   # NUMERIC de PostgreSQL llega como Decimal
            if df[c].map(lambda v: hasattr(v, "as_tuple")).any():
                df[c] = df[c].astype(float)
        figura = grafico(df, r.grafico)
        if figura is not None:
            st.altair_chart(figura.properties(title=r.titulo, height=320), width="stretch")
        with st.expander(f"Ver datos ({len(df)} filas)"):
            st.dataframe(df, width="stretch", hide_index=True)
            st.download_button("Descargar CSV", df.to_csv(index=False).encode("utf-8-sig"),
                               file_name="technova_consulta.csv", mime="text/csv", key=f"csv{id(r)}")
    if r.sql:
        titulo = "Ver SQL generado" + (" (autocorregido)" if r.sql_fallidos and not r.error else "")
        with st.expander(titulo):
            st.code(r.sql, language="sql")
            for fallo in r.sql_fallidos:
                st.caption(f"Primer intento descartado: {fallo['error']}")
                st.code(fallo["sql"], language="sql")
    st.caption(f"{r.segundos:.1f} s · {r.intentos} llamada(s) al modelo para el SQL")


# ---------------------------------------------------------------------
# Página
# ---------------------------------------------------------------------
try:
    num_tablas = preparar()
except Exception as e:   # sin base de datos no hay nada que hacer
    st.error(f"No se puede conectar con el data warehouse: {e}")
    st.stop()

if "historial" not in st.session_state:
    st.session_state.historial = []

with st.sidebar:
    st.markdown("## TechNova")
    st.caption("Asistente de datos en lenguaje natural")
    st.markdown(f"**Modelo:** {llm.proveedor()} · `{llm.modelo()}`  \n**Tablas disponibles:** {num_tablas}")
    st.divider()
    st.markdown("**Prueba con:**")
    for ejemplo in EJEMPLOS:
        if st.button(ejemplo, width="stretch"):
            st.session_state.pendiente = ejemplo
    st.divider()
    datos = estadisticas()
    if datos and datos[0]:
        st.metric("Preguntas respondidas", f"{datos[0]:,}".replace(",", "."))
        st.metric("Con SQL válido", f"{datos[1]:.0%}")
        st.metric("Tiempo medio", f"{datos[2]:.1f} s")
    if st.button("Nueva conversación", width="stretch"):
        st.session_state.historial = []
        st.rerun()

st.title("Pregunta a los datos de TechNova")
st.caption("Escribe una pregunta sobre ventas, clientes, productos, stock o RRHH (2023-2025). "
           "La IA la convierte en SQL, lo ejecuta con un usuario de solo lectura y te resume el resultado.")

for r in st.session_state.historial:
    with st.chat_message("user"):
        st.markdown(r.pregunta)
    with st.chat_message("assistant"):
        mostrar(r)

pregunta = st.chat_input("Por ejemplo: ¿qué categoría tuvo más margen en 2025?")
pregunta = pregunta or st.session_state.pop("pendiente", None)
if pregunta:
    with st.chat_message("user"):
        st.markdown(pregunta)
    with st.chat_message("assistant"):
        with st.spinner("Pensando la consulta..."):
            r = preguntar(pregunta, st.session_state.historial)
        mostrar(r)
    st.session_state.historial.append(r)
