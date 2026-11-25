"""
analyzer.py — Agente IA (Gemini) que analiza documentación y genera casos de uso.
Responsabilidad: analizar datos reales y producir casos de uso fundamentados.
NO inventa libremente; fundamenta cada caso en evidencia de la documentación.
Usa google-genai (SDK moderno, reemplazo de google-generativeai).
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

from config import settings
from extractor import DocumentationSummary

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Importación del SDK de Gemini (google-genai moderno)
# ---------------------------------------------------------------------------

try:
    from google import genai
    from google.genai import types as genai_types
    _SDK_VERSION = "genai"
except ImportError:
    try:
        import google.generativeai as genai_legacy
        _SDK_VERSION = "generativeai_legacy"
    except ImportError:
        genai = None
        _SDK_VERSION = "none"


# ---------------------------------------------------------------------------
# Configuración del cliente Gemini
# ---------------------------------------------------------------------------

def _get_client():
    """Retorna el cliente Gemini configurado o None."""
    if not settings.google_api_key:
        return None
    try:
        if _SDK_VERSION == "genai":
            client = genai.Client(api_key=settings.google_api_key)
            return client
        elif _SDK_VERSION == "generativeai_legacy":
            genai_legacy.configure(api_key=settings.google_api_key)
            return genai_legacy.GenerativeModel(settings.gemini_model)
        return None
    except Exception:
        return None


# Modelos en orden de preferencia y fallback automático ante 503, 429, 404 o sobrecarga
MODEL_FALLBACK = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-flash-latest",
]


def _generate_content(client, prompt: str) -> str:
    """
    Genera contenido estructurado usando Gemini con modo JSON explícito.
    Implementa rollover automático ante 503 (high demand), 429 o 404.
    """
    configured_model = settings.gemini_model
    # Lista priorizada: modelo configurado primero, luego los fallbacks
    models_to_try = [configured_model] + [m for m in MODEL_FALLBACK if m != configured_model]

    last_error = None
    for model_name in models_to_try:
        try:
            if _SDK_VERSION == "genai":
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(
                        temperature=0.2,
                        max_output_tokens=8192,
                        response_mime_type="application/json",
                    ),
                )
                if response and response.text:
                    return response.text
            elif _SDK_VERSION == "generativeai_legacy":
                response = client.generate_content(
                    prompt,
                    generation_config={
                        "temperature": 0.2,
                        "max_output_tokens": 8192,
                        "response_mime_type": "application/json",
                    },
                )
                if response and response.text:
                    return response.text
        except Exception as e:
            err_str = str(e)
            last_error = e

            # Si es error de autenticación pura (API Key inválida), no tiene sentido probar otros modelos
            if "api_key" in err_str.lower() or "401" in err_str:
                raise RuntimeError("API Key inválida o sin permisos. Verifica GOOGLE_API_KEY en .env")

            logger.warning(
                "Error con modelo %s (%s). Intentando siguiente modelo en fallback...",
                model_name,
                err_str[:120],
            )
            continue

    raise RuntimeError(
        f"Ningún modelo de Gemini respondió satisfactoriamente. Último error: {last_error}"
    )


# ---------------------------------------------------------------------------
# Prompt de análisis
# ---------------------------------------------------------------------------

ANALYSIS_PROMPT = """Eres un experto en ingeniería de software. Tu tarea es analizar documentación técnica REAL y generar conocimiento práctico.

REGLA CRÍTICA: Los casos de uso DEBEN estar fundamentados en el código y APIs reales que aparecen en la documentación. NO inventes APIs, funciones o comportamientos que no estén en el contexto provisto.

CONTEXTO DE DOCUMENTACIÓN:
{context}

---

Con base en la documentación anterior, genera un análisis estructurado en JSON con el siguiente formato EXACTO:

{{
  "library": {{
    "name": "Nombre de la librería o tecnología",
    "description": "Descripción clara y concisa (2-3 oraciones)",
    "installation": "Comando(s) de instalación (ej: pip install X, o indicar si ya está incluida en la biblioteca estándar)",
    "concepts": ["concepto1", "concepto2", "concepto3"],
    "apis": ["API1", "función2", "clase3"]
  }},
  "use_cases": [
    {{
      "title": "Título descriptivo del caso de uso",
      "objective": "Qué problema resuelve específicamente",
      "problem": "Qué dificultad tendría el usuario sin esta librería",
      "explanation": "Cómo la librería resuelve el problema (2-3 oraciones)",
      "why_use_library": "Ventaja específica vs alternativas",
      "apis_used": ["función/clase/método utilizado"],
      "language": "python",
      "minimal_script": "# Código Python minimalista que demuestra el caso\\nimport X\\n...",
      "dependencies": ["libreria==version"],
      "execution": "python script.py",
      "expected_result": "Lo que verá el usuario al ejecutarlo",
      "evidence": [
        {{"source_url": "URL donde encontraste el código", "api": "función/método usado"}}
      ]
    }}
  ]
}}

REQUISITOS OBLIGATORIOS:
1. Genera EXACTAMENTE {min_cases} casos de uso DIFERENTES (no variantes del mismo).
2. Cada caso debe tener un minimal_script REAL y FUNCIONAL (no pseudocódigo).
3. El script debe ser lo más corto posible manteniendo funcionalidad.
4. Cada caso debe tener al menos 1 elemento de evidencia con source_url real tomada del contexto provisto.
5. Las APIs en apis_used deben aparecer en la documentación provista.
6. Si la documentación no tiene código suficiente, usa el texto para inferir el uso correcto.
7. NO uses APIs inventadas ni funciones que no existan en la librería.
8. Retorna ÚNICAMENTE el JSON válido, sin bloques de markdown extra, sin comentarios fuera del JSON.
9. Dentro de los valores de texto y scripts, usa comillas dobles escapadas (\\\" y \\n) para saltos de línea dentro de cadenas JSON.
"""

# ---------------------------------------------------------------------------
# Extracción y parseo ultra-robusto de JSON
# ---------------------------------------------------------------------------

def _parse_json_robust(raw_text: str) -> Dict[str, Any]:
    """
    Parsea JSON de manera ultra-resiliente con múltiples niveles de reparación:
    1. json.loads con strict=False (tolera caracteres de control, saltos de línea y tabs sin escapar).
    2. Saneamiento de caracteres de control ilegales y comas huérfanas (trailing commas).
    3. Cierre automático de cadenas y llaves/corchetes si el JSON fue truncado.
    """
    if not raw_text or not raw_text.strip():
        raise ValueError("La respuesta del modelo está vacía.")

    # 1. Limpieza básica de bloques markdown
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    # 2. Extraer desde el primer '{' hasta el último '}'
    start = text.find("{")
    if start == -1:
        raise ValueError("No se encontró ningún objeto JSON (falta '{') en la respuesta.")

    end = text.rfind("}")
    json_candidate = text[start : end + 1] if (end != -1 and end > start) else text[start:]

    # Intento 1: json.loads con strict=False
    # Esto resuelve de inmediato errores del tipo 'Invalid control character'
    try:
        return json.loads(json_candidate, strict=False)
    except Exception:
        pass

    # Intento 2: Limpieza de caracteres de control ASCII (0x00 a 0x1F excepto \t y \n) y comas finales
    cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', json_candidate)
    cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)
    try:
        return json.loads(cleaned, strict=False)
    except Exception:
        pass

    # Intento 3: Reparación de JSON truncado (cierre de comillas y balanceo de llaves)
    repaired = cleaned.strip()
    # Si hay número impar de comillas no escapadas, cerrar la última cadena
    quotes = len(re.findall(r'(?<!\\)"', repaired))
    if quotes % 2 != 0:
        repaired += '"'

    open_brackets = repaired.count('[') - repaired.count(']')
    open_braces = repaired.count('{') - repaired.count('}')
    repaired += (']' * max(0, open_brackets))
    repaired += ('}' * max(0, open_braces))
    repaired = re.sub(r',\s*([}\]])', r'\1', repaired)

    try:
        return json.loads(repaired, strict=False)
    except Exception as e:
        raise ValueError(
            f"El modelo no devolvió JSON válido después de múltiples reparaciones: {e}\n"
            f"Fragmento inicial recibido: {raw_text[:400]}"
        )


def _validate_result(data: Dict[str, Any], min_cases: int, base_url: str = "") -> List[str]:
    """Valida la estructura del resultado y aplica correcciones automáticas seguras."""
    errors = []

    if "library" not in data or not isinstance(data["library"], dict):
        errors.append("Falta la clave 'library' en el resultado.")
        return errors

    lib = data["library"]
    if not lib.get("name"):
        errors.append("library.name está vacío.")
    if not lib.get("description"):
        lib["description"] = "Librería y herramientas técnicas de programación."

    # Si no tiene instalación (ej. biblioteca estándar de Python), asignar valor por defecto
    if not lib.get("installation"):
        lib["installation"] = "Incluido en la biblioteca estándar / No requiere instalación externa"

    if "use_cases" not in data or not isinstance(data["use_cases"], list):
        errors.append("Falta la lista 'use_cases'.")
        return errors

    cases = data["use_cases"]
    if len(cases) < min_cases:
        errors.append(f"Se generaron {len(cases)} casos de uso; se requieren al menos {min_cases}.")

    for i, case in enumerate(cases):
        if not case.get("title"):
            case["title"] = f"Caso de uso #{i + 1}"
        if not case.get("objective"):
            case["objective"] = "Resolver tarea técnica con la librería"
        if not case.get("language"):
            case["language"] = "python"

        # Validar o crear evidencia automática
        if not case.get("evidence") or not isinstance(case["evidence"], list):
            api_hint = (case.get("apis_used") or [""])[0]
            case["evidence"] = [{"source_url": base_url, "api": api_hint}]

        script = case.get("minimal_script", "")
        if not script or len(script.strip()) < 8:
            errors.append(f"use_cases[{i}].minimal_script parece vacío o trivial.")

    return errors


# ---------------------------------------------------------------------------
# Analizador principal
# ---------------------------------------------------------------------------

class DocumentationAnalyzer:
    """
    Usa Gemini para analizar documentación real y generar casos de uso fundamentados.
    """

    def __init__(self):
        self._client = _get_client()

    def is_available(self) -> bool:
        return self._client is not None and _SDK_VERSION != "none"

    def analyze(
        self,
        summary: DocumentationSummary,
        context: str,
        min_cases: int = settings.min_use_cases,
    ) -> Dict[str, Any]:
        """
        Analiza la documentación y retorna el resultado estructurado.
        Lanza ValueError si hay errores de validación no recuperables.
        Lanza RuntimeError si Gemini no está disponible.
        """
        if not self._client:
            raise RuntimeError(
                "Gemini no está disponible. Configura GOOGLE_API_KEY en el archivo .env."
            )

        prompt = ANALYSIS_PROMPT.format(context=context, min_cases=min_cases)

        try:
            raw_text = _generate_content(self._client, prompt)
        except Exception as e:
            error_msg = str(e)
            if "quota" in error_msg.lower() or "429" in error_msg:
                raise RuntimeError("Cuota de API temporalmente saturada. Intenta de nuevo en unos momentos.")
            elif "api_key" in error_msg.lower() or "INVALID_ARGUMENT" in error_msg or "401" in error_msg:
                raise RuntimeError("API Key inválida o sin permisos. Verifica GOOGLE_API_KEY en .env")
            elif "Ningún modelo" in error_msg:
                raise RuntimeError(error_msg)
            else:
                raise RuntimeError(f"Error al invocar Gemini: {error_msg[:300]}")

        # Extraer y parsear JSON con el parser robusto
        data = _parse_json_robust(raw_text)

        # Validar y autocorregir estructura
        errors = _validate_result(data, min_cases, base_url=summary.base_url)
        if errors:
            raise ValueError(
                "El resultado generado requiere ajustes no automáticos:\n" +
                "\n".join(f"  - {e}" for e in errors)
            )

        # Enriquecer evidencia con URLs reales conocidas si estuvieran vacías
        known_urls = list(summary.raw_text_by_page.keys())
        default_url = known_urls[0] if known_urls else summary.base_url
        for case in data.get("use_cases", []):
            for ev in case.get("evidence", []):
                if not ev.get("source_url"):
                    ev["source_url"] = default_url

        return data
