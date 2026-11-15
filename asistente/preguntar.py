"""
preguntar.py -> El asistente desde la terminal.

    python asistente/preguntar.py "¿Qué tienda vendió más en noviembre de 2025?"
    python asistente/preguntar.py                 # modo conversación (escribe 'salir' para terminar)
    python asistente/preguntar.py --modelos       # modelos de Gemini disponibles para tu clave
"""
import argparse
import sys

import pandas as pd

import bd
import llm
from asistente import preguntar


def mostrar(r):
    print()
    if r.sql:
        print("SQL generado" + (f" (corregido tras {r.intentos - 1} error)" if r.intentos > 1 and not r.error else "") + ":")
        print("   " + r.sql.replace("\n", "\n   "))
        print()
    if r.filas:
        tabla = pd.DataFrame(r.filas, columns=r.columnas)
        print(tabla.head(20).to_string(index=False))
        if len(tabla) > 20:
            print(f"... ({len(tabla)} filas en total)")
        print()
    print(r.texto)
    if r.error:
        print(f"\n[error] {r.error}")
    print(f"\n({r.segundos:.1f} s · {llm.proveedor()} {llm.modelo()})")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")   # tildes y € en la terminal de Windows
    parser = argparse.ArgumentParser(description="Pregunta a los datos de TechNova en lenguaje natural")
    parser.add_argument("pregunta", nargs="?", help="La pregunta (si no se indica, modo conversación)")
    parser.add_argument("--modelos", action="store_true", help="Lista los modelos de Gemini disponibles")
    args = parser.parse_args()

    if args.modelos:
        for m in llm.modelos_gemini():
            print(m)
        return

    bd.preparar()
    if args.pregunta:
        mostrar(preguntar(args.pregunta))
        return

    print(f"Asistente de datos de TechNova ({llm.proveedor()} · {llm.modelo()}). Escribe 'salir' para terminar.")
    historial = []
    while True:
        try:
            pregunta = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if pregunta.lower() in ("salir", "exit", "quit"):
            break
        if pregunta:
            r = preguntar(pregunta, historial)
            mostrar(r)
            historial.append(r)


if __name__ == "__main__":
    main()
