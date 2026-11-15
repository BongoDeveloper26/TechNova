"""
evaluar.py -> Mide cuántas preguntas responde bien el asistente ("execution accuracy").

Para cada pregunta de evaluacion.yml:
  1. El asistente genera su SQL (como en uso normal, con autocorrección)
  2. Se ejecutan su consulta y la de referencia
  3. Se comparan los RESULTADOS: mismo número de filas y, en cada fila, todos los valores de la
     referencia aparecen en la del asistente (puede tener columnas de más o en otro orden;
     los números se comparan redondeados)

    python asistente/evaluar.py               # todas las preguntas
    python asistente/evaluar.py --pausa 5     # segundos entre preguntas (capa gratuita de Gemini)

Escribe el resultado en docs/asistente_evaluacion.md.
"""
import argparse
import time
from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml

import bd
import llm
from asistente import preguntar
from seguridad import con_limite

RAIZ = Path(__file__).resolve().parent.parent
FICHERO = Path(__file__).with_name("evaluacion.yml")
INFORME = RAIZ / "docs" / "asistente_evaluacion.md"


def normalizar(valor):
    if isinstance(valor, (int, float, Decimal)) and not isinstance(valor, bool):
        return float(valor)
    if isinstance(valor, date):
        return valor.isoformat()
    return str(valor).strip().lower() if valor is not None else None


def mismo_valor(esperado, generado) -> bool:
    """Igualdad tolerante: los números pueden venir redondeados distinto o como porcentaje (0,253 o 25,3)."""
    if isinstance(esperado, float) and isinstance(generado, float):
        tolerancia = max(0.01, abs(esperado) * 0.001)
        return abs(esperado - generado) <= tolerancia or abs(esperado * 100 - generado) <= tolerancia * 100
    return esperado == generado


def coinciden(referencia, generado) -> bool:
    """Mismo número de filas y cada fila de la referencia está contenida en una fila del asistente."""
    if len(referencia) == 1 and len(generado) > 1:
        # Preguntas de "¿cuál es el que más...?": vale si el asistente da el ranking y el primero es el correcto
        generado = generado[:1]
    if len(referencia) != len(generado):
        return False
    restantes = [list(map(normalizar, f)) for f in generado]
    for fila in referencia:
        valores = list(map(normalizar, fila))
        encontrada = next((g for g in restantes
                           if all(any(mismo_valor(v, x) for x in g) for v in valores)), None)
        if encontrada is None:
            return False
        restantes.remove(encontrada)
    return True


def main():
    parser = argparse.ArgumentParser(description="Evalúa el asistente con preguntas de referencia")
    parser.add_argument("--pausa", type=float, default=4.0, help="Segundos entre preguntas")
    args = parser.parse_args()

    bd.preparar()
    casos = yaml.safe_load(FICHERO.read_text(encoding="utf-8"))
    resultados = []
    for i, caso in enumerate(casos, start=1):
        _, esperado = bd.ejecutar(con_limite(caso["sql"]))
        r = preguntar(caso["pregunta"], resumir=False, registrar=False)
        ok = r.error is None and r.filas is not None and coinciden(esperado, r.filas)
        resultados.append((caso["pregunta"], ok, r))
        print(f"[{'OK ' if ok else 'MAL'}] {i:>2}. {caso['pregunta']}" + (f"  ({r.error})" if r.error else ""))
        if not ok and r.sql:
            print("       " + r.sql.replace("\n", "\n       "))
        time.sleep(args.pausa)

    aciertos = sum(ok for _, ok, _ in resultados)
    autocorregidas = sum(1 for _, ok, r in resultados if ok and r.sql_fallidos)
    print(f"\n{aciertos} de {len(resultados)} correctas ({aciertos / len(resultados):.0%}); "
          f"{autocorregidas} gracias a la autocorrección")

    lineas = [
        "# Evaluación del asistente de datos", "",
        f"Modelo: `{llm.proveedor()} / {llm.modelo()}` · Fecha: {date.today():%d/%m/%Y}", "",
        f"**{aciertos} de {len(resultados)} preguntas correctas ({aciertos / len(resultados):.0%})**, "
        f"{autocorregidas} de ellas gracias a la autocorrección.", "",
        "Se compara el resultado de la consulta del asistente con el de una consulta de referencia "
        "escrita a mano (execution accuracy).", "",
        "| # | Pregunta | Resultado | Intentos |", "|---|---|---|---|",
    ]
    for i, (pregunta, ok, r) in enumerate(resultados, start=1):
        lineas.append(f"| {i} | {pregunta} | {'Correcta' if ok else 'Incorrecta'} | {r.intentos} |")
    fallos = [(i, p, r) for i, (p, ok, r) in enumerate(resultados, start=1) if not ok]
    if fallos:
        lineas += ["", "## Preguntas falladas", "", "El SQL que generó el asistente, para analizar el error:"]
        for i, pregunta, r in fallos:
            lineas += ["", f"**{i}. {pregunta}**", "", "```sql", r.sql or f"-- sin SQL: {r.error or r.texto}", "```"]
    INFORME.parent.mkdir(parents=True, exist_ok=True)
    INFORME.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print(f"Informe: {INFORME.relative_to(RAIZ).as_posix()}")


if __name__ == "__main__":
    main()