"""
markdown_generator.py — Generador de archivo .md compatible con Obsidian.
Responsabilidad: transformar el resultado estructurado en un Library Skill Markdown.
"""

from datetime import date
from typing import Any, Dict, List


class MarkdownGenerator:
    """
    Genera un archivo Markdown estructurado compatible con Obsidian
    a partir del resultado del DocumentationAnalyzer.
    """

    def generate(self, result: Dict[str, Any], source_url: str) -> str:
        """
        Genera el contenido completo del archivo .md.

        Args:
            result: Resultado validado del DocumentationAnalyzer.
            source_url: URL original de la documentación.

        Returns:
            String con el contenido completo del Markdown.
        """
        lib = result.get("library", {})
        use_cases: List[Dict] = result.get("use_cases", [])

        name = lib.get("name", "Librería")
        description = lib.get("description", "")
        installation = lib.get("installation", "")
        concepts: List[str] = lib.get("concepts", [])
        apis: List[str] = lib.get("apis", [])
        today = date.today().isoformat()

        # Construir tags a partir del nombre de la librería
        lib_tag = name.lower().replace(" ", "-").replace(".", "")
        # Detectar lenguaje predominante
        languages = [uc.get("language", "python") for uc in use_cases]
        main_lang = max(set(languages), key=languages.count) if languages else "python"

        parts = []

        # ── Frontmatter YAML ──────────────────────────────────────────────
        parts.append(f"""---
aliases: [{name}]
tags:
  - library-skill
  - {lib_tag}
  - {main_lang}
created: "{today}"
type: library-skill
status: completo
difficulty: intermedio
source: "{source_url}"
generated_at: "{today}"
language: {main_lang}
---

""")

        # ── Título ────────────────────────────────────────────────────────
        parts.append(f"# {name}\n\n")
        parts.append(f"> Documentación generada automáticamente desde [{source_url}]({source_url})  \n")
        parts.append(f"> Fecha: {today}\n\n")

        # ── Descripción ──────────────────────────────────────────────────
        parts.append("## Descripción\n\n")
        parts.append(f"{description}\n\n")

        # ── Instalación ──────────────────────────────────────────────────
        parts.append("## Instalación\n\n")
        parts.append(f"```bash\n{installation}\n```\n\n")

        # ── Conceptos principales ────────────────────────────────────────
        if concepts:
            parts.append("## Conceptos principales\n\n")
            for c in concepts:
                parts.append(f"- {c}\n")
            parts.append("\n")

        # ── APIs / Funciones importantes ─────────────────────────────────
        if apis:
            parts.append("## APIs / Funciones importantes\n\n")
            for api in apis:
                parts.append(f"- `{api}`\n")
            parts.append("\n")

        # ── Casos de uso ─────────────────────────────────────────────────
        parts.append("---\n\n# Casos de uso\n\n")

        for i, case in enumerate(use_cases, 1):
            title = case.get("title", f"Caso {i}")
            objective = case.get("objective", "")
            problem = case.get("problem", "")
            explanation = case.get("explanation", "")
            why = case.get("why_use_library", "")
            apis_used: List[str] = case.get("apis_used", [])
            language = case.get("language", "python")
            script = case.get("minimal_script", "")
            dependencies: List[str] = case.get("dependencies", [])
            execution = case.get("execution", "")
            expected = case.get("expected_result", "")
            evidence: List[Dict] = case.get("evidence", [])

            parts.append(f"## Caso de uso {i} — {title}\n\n")

            parts.append(f"### Objetivo\n\n{objective}\n\n")
            parts.append(f"### Problema\n\n{problem}\n\n")
            parts.append(f"### Explicación\n\n{explanation}\n\n")
            parts.append(f"### Por qué usar {name}\n\n{why}\n\n")

            if apis_used:
                parts.append("### APIs utilizadas\n\n")
                for api in apis_used:
                    parts.append(f"- `{api}`\n")
                parts.append("\n")

            parts.append(f"### Script minimalista\n\n")
            parts.append(f"```{language}\n{script}\n```\n\n")

            if dependencies:
                parts.append("### Dependencias\n\n")
                parts.append(f"```bash\npip install {' '.join(dependencies)}\n```\n\n")

            if execution:
                parts.append(f"### Ejecución\n\n```bash\n{execution}\n```\n\n")

            if expected:
                parts.append(f"### Resultado esperado\n\n{expected}\n\n")

            if evidence:
                parts.append("### Evidencia\n\n")
                for ev in evidence:
                    url_ev = ev.get("source_url", "")
                    api_ev = ev.get("api", "")
                    if url_ev:
                        line = f"- [{url_ev}]({url_ev})"
                        if api_ev:
                            line += f" — `{api_ev}`"
                        parts.append(line + "\n")
                parts.append("\n")

            if i < len(use_cases):
                parts.append("---\n\n")

        # ── Tecnologías relacionadas (wikilinks Obsidian) ─────────────────
        parts.append("\n---\n\n## Tecnologías relacionadas\n\n")
        # Generar wikilinks a partir de las APIs y conceptos
        related_set = set()
        for api in (apis or [])[:5]:
            related_set.add(api.split(".")[0].strip())
        related_set.discard(name)
        for r in related_set:
            if r:
                parts.append(f"- [[{r}]]\n")
        parts.append(f"- [[{main_lang.capitalize()}]]\n")
        parts.append("\n")

        # ── Referencias ──────────────────────────────────────────────────
        parts.append("## Referencias\n\n")
        parts.append(f"- [Documentación oficial]({source_url})\n")

        # URLs únicas de evidencia
        evidence_urls = set()
        for case in use_cases:
            for ev in case.get("evidence", []):
                u = ev.get("source_url", "")
                if u and u != source_url:
                    evidence_urls.add(u)
        for u in sorted(evidence_urls)[:5]:
            parts.append(f"- [{u}]({u})\n")

        parts.append("\n")

        return "".join(parts)

    def filename_for(self, library_name: str) -> str:
        """Genera un nombre de archivo seguro para el Markdown."""
        safe = library_name.strip().replace(" ", "-").replace("/", "-")
        import re
        safe = re.sub(r"[^a-zA-Z0-9\-_]", "", safe)
        return f"{safe}.md" if safe else "library-skill.md"
