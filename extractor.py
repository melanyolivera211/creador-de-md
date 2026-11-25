"""
extractor.py — Extractor de conocimiento estructurado desde páginas scrapeadas.
Responsabilidad: transformar PageData en CodeSnippet estructurados y resumen de documentación.
"""

from dataclasses import asdict, dataclass
from typing import Any, Dict, List

from scraper import CodeBlock, PageData


# ---------------------------------------------------------------------------
# Estructura de salida
# ---------------------------------------------------------------------------

@dataclass
class CodeSnippet:
    """Fragmento de código con todo el contexto extraído."""
    source_url: str
    language: str
    code: str
    section: str
    description: str
    api: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DocumentationSummary:
    """Resumen completo de la documentación extraída."""
    base_url: str
    total_pages: int
    snippets: List[CodeSnippet]
    raw_text_by_page: Dict[str, str]   # url -> texto limpio
    page_titles: Dict[str, str]        # url -> título


# ---------------------------------------------------------------------------
# Extractor principal
# ---------------------------------------------------------------------------

class CodeExtractor:
    """
    Transforma una lista de PageData en una DocumentationSummary estructurada.
    Elimina duplicados y organiza el conocimiento por relevancia.
    """

    def extract(self, pages: List[PageData]) -> DocumentationSummary:
        """Procesa todas las páginas y retorna la documentación estructurada."""
        snippets: List[CodeSnippet] = []
        seen_code_hashes = set()

        raw_text_by_page: Dict[str, str] = {}
        page_titles: Dict[str, str] = {}

        for page in pages:
            raw_text_by_page[page.url] = page.text_content
            page_titles[page.url] = page.title

            for block in page.code_blocks:
                # Deduplicar por contenido
                code_key = hash(block.code[:300])
                if code_key in seen_code_hashes:
                    continue
                seen_code_hashes.add(code_key)

                snippets.append(CodeSnippet(
                    source_url=block.source_url,
                    language=block.language,
                    code=block.code,
                    section=block.section,
                    description=block.description,
                    api=block.api,
                ))

        # Ordenar: primero Python/JS/bash (más útiles para casos de uso), luego el resto
        lang_priority = {"python": 0, "javascript": 1, "bash": 2, "typescript": 3}
        snippets.sort(key=lambda s: (lang_priority.get(s.language, 10), -len(s.code)))

        base_url = pages[0].url if pages else ""

        return DocumentationSummary(
            base_url=base_url,
            total_pages=len(pages),
            snippets=snippets,
            raw_text_by_page=raw_text_by_page,
            page_titles=page_titles,
        )

    def build_context_for_ai(self, summary: DocumentationSummary, max_chars: int = 40000) -> str:
        """
        Construye el contexto de texto para enviar a Gemini.
        Combina texto de páginas prioritarias + bloques de código relevantes.
        """
        parts = []
        chars_used = 0

        # === TEXTO DE PÁGINAS ===
        parts.append("## DOCUMENTACIÓN EXTRAÍDA\n")
        for url, text in list(summary.raw_text_by_page.items())[:12]:
            title = summary.page_titles.get(url, url)
            chunk = f"\n### [{title}]({url})\n{text[:2500]}\n"
            if chars_used + len(chunk) > max_chars * 0.55:
                break
            parts.append(chunk)
            chars_used += len(chunk)

        # === BLOQUES DE CÓDIGO ===
        parts.append("\n\n## CÓDIGO REAL EXTRAÍDO DE LA DOCUMENTACIÓN\n")
        for i, snippet in enumerate(summary.snippets[:40]):
            block = (
                f"\n### Snippet {i+1} [{snippet.language}] — {snippet.section}\n"
                f"Fuente: {snippet.source_url}\n"
                f"API/Función: {snippet.api or 'N/A'}\n"
                f"Descripción: {snippet.description[:200] or 'N/A'}\n"
                f"```{snippet.language}\n{snippet.code[:800]}\n```\n"
            )
            if chars_used + len(block) > max_chars:
                break
            parts.append(block)
            chars_used += len(block)

        return "".join(parts)
