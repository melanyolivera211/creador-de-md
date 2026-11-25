"""
app.py — Punto de entrada del Agente-Scapper.
Backend FastAPI + servidor de archivos estáticos.
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl

from agent_connector import AgentConnector
from analyzer import DocumentationAnalyzer
from config import settings
from extractor import CodeExtractor
from markdown_generator import MarkdownGenerator
from scraper import DocScraper

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Agente-Scapper",
    description="Extractor de Conocimiento Técnico desde Documentación",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Servir frontend estático
frontend_path = Path(__file__).parent / "frontend"
if frontend_path.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_path)), name="static")

# ---------------------------------------------------------------------------
# In-memory session store (sin base de datos)
# ---------------------------------------------------------------------------
# Almacena el último resultado por sesión/análisis
_last_result: Dict[str, Any] = {}
_last_markdown: str = ""
_last_library_name: str = ""

# ---------------------------------------------------------------------------
# Modelos Pydantic
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    url: str


class SendToAgentRequest(BaseModel):
    markdown_content: str
    filename: str


# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def root():
    """Sirve la página principal."""
    index = frontend_path / "index.html"
    if index.exists():
        return HTMLResponse(content=index.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Agente-Scapper</h1><p>Frontend no encontrado.</p>")


@app.get("/api/health")
async def health():
    """Estado del servidor."""
    connector = AgentConnector()
    return {
        "status": "ok",
        "gemini_configured": bool(settings.google_api_key),
        "gemini_model": settings.gemini_model,
        "mi_agente": connector.get_status(),
        "config": {
            "max_pages": settings.max_pages,
            "max_depth": settings.max_depth,
            "min_use_cases": settings.min_use_cases,
        },
    }


@app.post("/api/analyze")
async def analyze(request: AnalyzeRequest):
    """
    Ejecuta el pipeline completo:
    URL → Scraping → Extracción → Análisis IA → Casos de uso

    Retorna Server-Sent Events con progreso en tiempo real.
    """
    url = request.url.strip()

    async def event_stream():
        global _last_result, _last_markdown, _last_library_name

        def send_event(event_type: str, data: dict):
            payload = json.dumps({"type": event_type, **data})
            return f"data: {payload}\n\n"

        # ── Paso 1: Validar URL ────────────────────────────────────────
        yield send_event("progress", {
            "step": "validating",
            "message": "🔗 Validando URL...",
            "percent": 5,
        })
        await asyncio.sleep(0.1)

        scraper = DocScraper()
        ok, error = scraper.validate_url(url)
        if not ok:
            yield send_event("error", {"message": error})
            return

        yield send_event("progress", {
            "step": "validated",
            "message": "✅ URL válida y accesible.",
            "percent": 10,
        })

        # ── Paso 2: Scraping ──────────────────────────────────────────
        yield send_event("progress", {
            "step": "scraping",
            "message": "🕷️ Iniciando scraping de la documentación...",
            "percent": 15,
        })
        await asyncio.sleep(0.1)

        pages = []
        pages_done = 0

        try:
            for event in scraper.scrape(url):
                if event["type"] == "progress":
                    yield send_event("progress", {
                        "step": "scraping",
                        "message": event["message"],
                        "percent": min(15 + pages_done * 2, 45),
                    })
                    await asyncio.sleep(0)
                elif event["type"] == "page":
                    pages_done += 1
                    yield send_event("progress", {
                        "step": "scraping",
                        "message": f"📄 Página {pages_done}: {event['title'][:50]} ({event['code_count']} bloques de código)",
                        "percent": min(15 + pages_done * 2, 45),
                    })
                    await asyncio.sleep(0)
                elif event["type"] == "done":
                    pages = event["pages"]
                    yield send_event("progress", {
                        "step": "scraped",
                        "message": f"✅ Scraping completado: {event['total_pages']} páginas, {event['total_code_blocks']} bloques de código.",
                        "percent": 45,
                    })
        except Exception as e:
            yield send_event("error", {
                "message": f"Error durante el scraping: {str(e)}"
            })
            return

        if not pages:
            yield send_event("error", {
                "message": "No se pudo extraer contenido. El sitio puede bloquear scrapers o no tener contenido HTML accesible."
            })
            return

        # ── Paso 3: Extracción ────────────────────────────────────────
        yield send_event("progress", {
            "step": "extracting",
            "message": "🔍 Extrayendo código y APIs...",
            "percent": 50,
        })
        await asyncio.sleep(0.1)

        extractor = CodeExtractor()
        summary = extractor.extract(pages)
        context = extractor.build_context_for_ai(summary)

        yield send_event("progress", {
            "step": "extracted",
            "message": f"✅ Extracción: {len(summary.snippets)} fragmentos de código identificados.",
            "percent": 58,
        })

        if not summary.snippets:
            yield send_event("progress", {
                "step": "extracting",
                "message": "⚠️ No se encontraron bloques de código. Se usará el texto de la documentación.",
                "percent": 58,
            })

        # ── Paso 4: Análisis IA ───────────────────────────────────────
        yield send_event("progress", {
            "step": "analyzing",
            "message": "🤖 Analizando documentación con Gemini...",
            "percent": 62,
        })
        await asyncio.sleep(0.1)

        analyzer = DocumentationAnalyzer()
        if not analyzer.is_available():
            yield send_event("error", {
                "message": "Gemini no configurado. Agrega GOOGLE_API_KEY al archivo .env."
            })
            return

        try:
            result = analyzer.analyze(summary, context)
        except RuntimeError as e:
            yield send_event("error", {"message": str(e)})
            return
        except ValueError as e:
            yield send_event("error", {
                "message": f"El modelo devolvió una respuesta inválida: {str(e)}"
            })
            return

        yield send_event("progress", {
            "step": "analyzed",
            "message": f"✅ Análisis completado: {len(result.get('use_cases', []))} casos de uso generados.",
            "percent": 82,
        })

        # ── Paso 5: Markdown ─────────────────────────────────────────
        yield send_event("progress", {
            "step": "generating_md",
            "message": "📝 Generando Markdown para Obsidian...",
            "percent": 88,
        })
        await asyncio.sleep(0.1)

        gen = MarkdownGenerator()
        markdown_content = gen.generate(result, url)
        filename = gen.filename_for(result.get("library", {}).get("name", "library"))

        # Guardar en memoria
        _last_result = result
        _last_markdown = markdown_content
        _last_library_name = filename

        yield send_event("progress", {
            "step": "done",
            "message": "✅ ¡Proceso completado!",
            "percent": 100,
        })
        await asyncio.sleep(0.1)

        # ── Resultado final ──────────────────────────────────────────
        yield send_event("result", {
            "result": result,
            "markdown": markdown_content,
            "filename": filename,
            "stats": {
                "pages_scraped": summary.total_pages,
                "code_snippets": len(summary.snippets),
                "use_cases": len(result.get("use_cases", [])),
            },
        })

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/export-markdown")
async def export_markdown(request: dict):
    """
    Retorna el Markdown como archivo descargable.
    Acepta el markdown en el body o usa el último generado.
    """
    global _last_markdown, _last_library_name

    markdown_content = request.get("markdown_content") or _last_markdown
    filename = request.get("filename") or _last_library_name or "library-skill.md"

    if not markdown_content:
        raise HTTPException(status_code=400, detail="No hay Markdown generado. Ejecuta un análisis primero.")

    return JSONResponse({
        "markdown": markdown_content,
        "filename": filename,
    })


@app.post("/api/send-to-agent")
async def send_to_agent(request: SendToAgentRequest):
    """
    Envía el Markdown generado a la bóveda de MI-AGENTE.
    """
    connector = AgentConnector()

    if not connector.is_available():
        status = connector.get_status()
        raise HTTPException(
            status_code=503,
            detail=status.get("error", "MI-AGENTE no disponible.")
        )

    success, message = connector.send_note(request.markdown_content, request.filename)

    if not success:
        raise HTTPException(status_code=500, detail=message)

    return {"success": True, "message": message}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 60)
    print("  AGENTE-SCAPPER -- Extractor de Conocimiento Tecnico")
    print("=" * 60)
    print(f"  URL: http://{settings.host}:{settings.port}")
    print(f"  Modelo Gemini: {settings.gemini_model}")
    print(f"  API Key: {'[OK] Configurada' if settings.google_api_key else '[!!] NO configurada (.env)'}")
    print(f"  MI-AGENTE: {settings.mi_agente_path}")
    print("=" * 60)

    uvicorn.run(
        "app:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info",
    )

