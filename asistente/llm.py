"""
llm.py -> Conexión con el modelo de lenguaje (LLM), sea cual sea el proveedor.

El resto del asistente solo llama a  llm.generar(sistema, mensaje)  y no sabe a quién
se lo pide. El proveedor se elige con una línea del .env:

    LLM_PROVEEDOR=gemini     # Google Gemini (tiene capa gratuita)    -> GEMINI_API_KEY, GEMINI_MODELO
    LLM_PROVEEDOR=claude     # API de Anthropic (de pago)             -> ANTHROPIC_API_KEY, CLAUDE_MODELO
    LLM_PROVEEDOR=ollama     # modelo local, gratis y sin internet    -> OLLAMA_URL, OLLAMA_MODELO

Se usan las API REST directamente con requests (sin los SDK de cada empresa), así que
añadir otro proveedor es escribir una función más.
"""
import json
import os
import re
import time

import requests

TIEMPO_MAXIMO = 60          # segundos de espera por respuesta
REINTENTOS = 4              # si el proveedor dice "demasiadas peticiones" (429) o falla un momento (5xx)

POR_DEFECTO = {
    "gemini": "gemini-3.5-flash-lite",   # capa gratuita con más peticiones al día que los Flash normales
    "claude": "claude-haiku-5-5",
    "ollama": "qwen2.5-coder:7b",
}


class ErrorLLM(RuntimeError):
    """El proveedor no ha respondido o ha respondido algo inesperado."""


def proveedor() -> str:
    nombre = os.getenv("LLM_PROVEEDOR", "gemini").strip().lower()
    if nombre not in POR_DEFECTO:
        raise ErrorLLM(f"LLM_PROVEEDOR='{nombre}' no es válido: usa gemini, claude u ollama")
    return nombre


def modelo() -> str:
    p = proveedor()
    variable = {"gemini": "GEMINI_MODELO", "claude": "CLAUDE_MODELO", "ollama": "OLLAMA_MODELO"}[p]
    return os.getenv(variable) or POR_DEFECTO[p]


def _clave(variable: str) -> str:
    clave = os.getenv(variable, "").strip()
    if not clave:
        raise ErrorLLM(f"Falta {variable} en el .env (la clave de la API de {proveedor()})")
    return clave


def _peticion(metodo, url, **kwargs) -> dict:
    """Petición HTTP con reintentos y espera progresiva si el proveedor nos pide frenar."""
    for intento in range(REINTENTOS + 1):
        try:
            r = requests.request(metodo, url, timeout=TIEMPO_MAXIMO, **kwargs)
        except requests.RequestException as e:
            if intento == REINTENTOS:
                raise ErrorLLM(f"No se puede conectar con {url.split('?')[0]}: {e}") from e
            time.sleep(2 ** intento)
            continue
        if r.status_code == 429 or r.status_code >= 500:
            if intento == REINTENTOS:
                raise ErrorLLM(f"El proveedor sigue respondiendo {r.status_code}: {r.text[:300]}")
            # La capa gratuita de Gemini limita las peticiones por minuto: esperamos y repetimos
            espera = float(r.headers.get("retry-after", 0) or 0) or min(60, 5 * 2 ** intento)
            time.sleep(espera)
            continue
        if r.status_code >= 400:
            raise ErrorLLM(f"Error {r.status_code} de {proveedor()}: {r.text[:500]}")
        return r.json()


# ---------------------------------------------------------------------
# Proveedores
# ---------------------------------------------------------------------

def _gemini(sistema, mensaje, json_salida):
    url = f"{os.getenv('GEMINI_URL', 'https://generativelanguage.googleapis.com/v1beta')}/models/{modelo()}:generateContent"
    cuerpo = {
        "systemInstruction": {"parts": [{"text": sistema}]},
        "contents": [{"role": "user", "parts": [{"text": mensaje}]}],
        "generationConfig": {"temperature": 0},
    }
    if json_salida:
        cuerpo["generationConfig"]["responseMimeType"] = "application/json"
    datos = _peticion("POST", url, json=cuerpo, headers={"x-goog-api-key": _clave("GEMINI_API_KEY")})
    try:
        return "".join(p.get("text", "") for p in datos["candidates"][0]["content"]["parts"])
    except (KeyError, IndexError) as e:
        raise ErrorLLM(f"Respuesta de Gemini sin texto: {json.dumps(datos)[:500]}") from e


def _claude(sistema, mensaje, json_salida):
    datos = _peticion(
        "POST", os.getenv("ANTHROPIC_URL", "https://api.anthropic.com/v1/messages"),
        headers={"x-api-key": _clave("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01"},
        json={"model": modelo(), "max_tokens": 2000, "temperature": 0, "system": sistema,
              "messages": [{"role": "user", "content": mensaje}]},
    )
    return "".join(b.get("text", "") for b in datos.get("content", []) if b.get("type") == "text")


def _ollama(sistema, mensaje, json_salida):
    cuerpo = {"model": modelo(), "stream": False, "options": {"temperature": 0},
              "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": mensaje}]}
    if json_salida:
        cuerpo["format"] = "json"
    datos = _peticion("POST", f"{os.getenv('OLLAMA_URL', 'http://localhost:11434')}/api/chat", json=cuerpo)
    return datos.get("message", {}).get("content", "")


PROVEEDORES = {"gemini": _gemini, "claude": _claude, "ollama": _ollama}


def generar(sistema: str, mensaje: str, json_salida: bool = False) -> str:
    """Devuelve el texto que genera el modelo para ese mensaje."""
    return PROVEEDORES[proveedor()](sistema, mensaje, json_salida)


def extraer_json(texto: str) -> dict:
    """
    Convierte la respuesta en un diccionario aunque el modelo la envuelva en ```json ... ```
    o escriba algo antes o después (pasa con los modelos pequeños).
    """
    texto = texto.strip()
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto)
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        inicio, fin = texto.find("{"), texto.rfind("}")
        if inicio != -1 and fin > inicio:
            try:
                return json.loads(texto[inicio:fin + 1])
            except json.JSONDecodeError:
                pass
    raise ErrorLLM(f"El modelo no ha devuelto un JSON válido: {texto[:300]}")


def modelos_gemini() -> list[str]:
    """Modelos de Gemini disponibles para tu clave que sirven para generar texto."""
    url = f"{os.getenv('GEMINI_URL', 'https://generativelanguage.googleapis.com/v1beta')}/models?pageSize=200"
    datos = _peticion("GET", url, headers={"x-goog-api-key": _clave("GEMINI_API_KEY")})
    return sorted(m["name"].removeprefix("models/") for m in datos.get("models", [])
                  if "generateContent" in m.get("supportedGenerationMethods", []))
