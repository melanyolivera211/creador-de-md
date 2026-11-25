"""
scraper.py — Scraper controlado de documentación técnica.
Responsabilidad: obtener y estructurar páginas de documentación.
Usa requests + BeautifulSoup. No utiliza AGENTE-MEDICO.
"""

import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Generator, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from config import settings

# ---------------------------------------------------------------------------
# Palabras clave de alta prioridad (páginas con contenido práctico)
# ---------------------------------------------------------------------------
PRIORITY_KEYWORDS = [
    "quickstart", "quick-start", "getting-started", "getting_started",
    "installation", "install", "tutorial", "guide", "examples", "example",
    "api-reference", "api_reference", "reference", "usage", "cookbook",
    "introduction", "intro", "overview", "basics", "start",
]

SKIP_PATTERNS = [
    r"/blog/", r"/news/", r"/changelog/", r"/release",
    r"/community/", r"/forum/", r"/discuss", r"/support",
    r"/download/", r"/pricing/", r"/about/", r"/team/",
    r"\.pdf$", r"\.zip$", r"\.tar\.gz$", r"\.png$", r"\.jpg$",
    r"#",  # anchors only
]

# ---------------------------------------------------------------------------
# Modelo de datos
# ---------------------------------------------------------------------------

@dataclass
class CodeBlock:
    """Un bloque de código extraído de una página."""
    code: str
    language: str = ""
    section: str = ""
    description: str = ""
    api: str = ""
    source_url: str = ""


@dataclass
class PageData:
    """Datos estructurados extraídos de una página de documentación."""
    url: str
    title: str
    text_content: str
    code_blocks: List[CodeBlock] = field(default_factory=list)
    priority: int = 0          # mayor = más importante


# ---------------------------------------------------------------------------
# Utilidades de URL
# ---------------------------------------------------------------------------

def _normalize_url(url: str) -> str:
    """Normaliza la URL eliminando fragmentos y trailing slashes innecesarios."""
    parsed = urlparse(url)
    # Quitar fragmento (#section)
    clean = urlunparse(parsed._replace(fragment=""))
    return clean.rstrip("/") if clean.endswith("/") and parsed.path != "/" else clean


def _same_domain(url: str, base_domain: str) -> bool:
    """Comprueba que la URL pertenezca al mismo dominio base."""
    return urlparse(url).netloc == base_domain


def _is_skippable(url: str) -> bool:
    """Retorna True si la URL debe omitirse."""
    path = urlparse(url).path.lower()
    for pattern in SKIP_PATTERNS:
        if re.search(pattern, path):
            return True
    return False


def _priority_score(url: str) -> int:
    """Puntúa la URL según palabras clave de alta relevancia."""
    path_lower = urlparse(url).path.lower()
    score = 0
    for kw in PRIORITY_KEYWORDS:
        if kw in path_lower:
            score += 10
    return score


# ---------------------------------------------------------------------------
# Detección de lenguaje
# ---------------------------------------------------------------------------

LANG_HINTS = {
    "python": ["python", "py"],
    "javascript": ["javascript", "js", "node", "nodejs"],
    "typescript": ["typescript", "ts"],
    "bash": ["bash", "shell", "sh", "zsh", "console", "terminal", "cmd", "powershell"],
    "json": ["json"],
    "yaml": ["yaml", "yml"],
    "go": ["go", "golang"],
    "rust": ["rust", "rs"],
    "java": ["java"],
    "cpp": ["cpp", "c++", "cxx"],
    "c": [" c "],
    "ruby": ["ruby", "rb"],
    "php": ["php"],
    "swift": ["swift"],
    "kotlin": ["kotlin"],
    "sql": ["sql"],
    "html": ["html"],
    "css": ["css"],
    "dockerfile": ["dockerfile"],
}

LANG_HEURISTICS = {
    "python": [r"^\s*import\s+\w+", r"^\s*from\s+\w+\s+import", r"def \w+\(", r"print\("],
    "javascript": [r"const\s+\w+\s*=", r"let\s+\w+\s*=", r"function\s+\w+\(", r"=>\s*{", r"require\("],
    "bash": [r"^\s*\$\s+", r"^#!/bin/(bash|sh)", r"\becho\b", r"\bexport\b"],
    "json": [r'^\s*[\[{]', r'":\s*["\d\[{]'],
    "yaml": [r"^\w[\w\s]*:\s+\S", r"^\s+-\s+\w"],
}


def detect_language(tag: "BeautifulSoup", code_text: str) -> str:  # noqa
    """Detecta el lenguaje de un bloque de código."""
    # 1. Clase CSS del elemento <code> o <pre>
    classes = []
    for cls_source in [tag, tag.find("code") if tag.name == "pre" else None]:
        if cls_source:
            classes.extend(cls_source.get("class", []))

    for cls in classes:
        cls_lower = cls.lower()
        # language-python, lang-python, highlight-python, python, etc.
        for lang, hints in LANG_HINTS.items():
            for hint in hints:
                if hint in cls_lower:
                    return lang

    # 2. Data attributes
    data_lang = tag.get("data-language", "") or tag.get("data-lang", "")
    if data_lang:
        return data_lang.lower()

    # 3. Heurísticas sobre el código
    sample = code_text[:500]
    for lang, patterns in LANG_HEURISTICS.items():
        for pattern in patterns:
            if re.search(pattern, sample, re.MULTILINE):
                return lang

    return "text"


# ---------------------------------------------------------------------------
# Extractor de texto limpio
# ---------------------------------------------------------------------------

NOISE_SELECTORS = [
    "nav", "header", "footer", ".sidebar", ".nav", ".navigation",
    ".toc", ".table-of-contents", ".breadcrumb", ".pagination",
    "[role=navigation]", "[role=banner]", "[role=contentinfo]",
    "script", "style", "noscript", "iframe",
]


def _extract_clean_text(soup: BeautifulSoup) -> str:
    """Extrae texto limpio eliminando navegación y ruido."""
    for selector in NOISE_SELECTORS:
        for el in soup.select(selector):
            el.decompose()
    # Tomar el contenido principal si existe
    main = soup.find("main") or soup.find("article") or soup.find(".content") or soup.body
    if not main:
        return ""
    text = main.get_text(separator="\n", strip=True)
    # Colapsar líneas vacías múltiples
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:8000]  # límite razonable por página


# ---------------------------------------------------------------------------
# Extracción de bloques de código
# ---------------------------------------------------------------------------

def _get_surrounding_text(tag, char_limit: int = 200) -> str:
    """Obtiene el texto circundante a un bloque de código como descripción."""
    context_parts = []
    # Texto del párrafo o encabezado anterior
    for sibling in tag.find_all_previous(["p", "h1", "h2", "h3", "h4", "li"], limit=3):
        txt = sibling.get_text(strip=True)
        if txt and len(txt) > 10:
            context_parts.append(txt)
    if context_parts:
        return " ".join(reversed(context_parts))[:char_limit]
    return ""


def _get_section_title(tag) -> str:
    """Obtiene el título de la sección más cercana."""
    for heading in tag.find_all_previous(["h1", "h2", "h3", "h4"], limit=1):
        return heading.get_text(strip=True)
    return ""


def _detect_api_name(code_text: str) -> str:
    """Intenta detectar el nombre de función o clase principal en el código."""
    patterns = [
        r"def\s+(\w+)\s*\(",           # Python def
        r"class\s+(\w+)",               # class
        r"(\w+)\s*=\s*\w+\.(\w+)\(",   # result = lib.method(
        r"import\s+(\w+)",              # import lib
        r"from\s+\w+\s+import\s+(\w+)",# from x import y
        r"(\w+)\.(get|post|put|delete|patch)\(",  # REST
        r"@app\.(get|post|put|delete)\(",          # Flask/FastAPI route
    ]
    for pattern in patterns:
        m = re.search(pattern, code_text[:500])
        if m:
            return m.group(1)
    return ""


def extract_code_blocks(soup: BeautifulSoup, url: str, page_title: str) -> List[CodeBlock]:
    """Extrae todos los bloques de código de una página."""
    blocks: List[CodeBlock] = []
    seen_codes: Set[str] = set()

    # Priorizar <pre><code> y luego <code> solitario largo
    for tag in soup.find_all(["pre", "code"]):
        code_tag = tag.find("code") if tag.name == "pre" else tag
        if not code_tag:
            code_tag = tag

        code_text = code_tag.get_text()
        code_clean = code_text.strip()

        # Filtrar bloques triviales o ya vistos
        if len(code_clean) < 15:
            continue
        code_hash = hash(code_clean[:200])
        if code_hash in seen_codes:
            continue
        seen_codes.add(code_hash)

        # Solo <code> inline si son suficientemente largos
        if tag.name == "code" and tag.parent and tag.parent.name not in ["pre"]:
            if len(code_clean) < 60:
                continue

        language = detect_language(tag, code_clean)
        section = _get_section_title(tag)
        description = _get_surrounding_text(tag)
        api = _detect_api_name(code_clean)

        blocks.append(CodeBlock(
            code=code_clean[:3000],  # límite razonable
            language=language,
            section=section or page_title,
            description=description,
            api=api,
            source_url=url,
        ))

    return blocks


# ---------------------------------------------------------------------------
# Scraper principal
# ---------------------------------------------------------------------------

class DocScraper:
    """
    Scraper controlado de documentación técnica.
    BFS con límite de páginas, profundidad y respeto de dominio.
    """

    def __init__(
        self,
        max_pages: int = settings.max_pages,
        max_depth: int = settings.max_depth,
        timeout: int = settings.request_timeout,
    ):
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (compatible; DocScraper/1.0; "
                "+https://github.com/academic-project)"
            ),
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
            "Accept-Language": "en,es;q=0.9",
        })

    # ------------------------------------------------------------------
    def validate_url(self, url: str) -> Tuple[bool, str]:
        """
        Valida que la URL sea accesible.
        Retorna (ok, error_message).
        """
        try:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                return False, "URL inválida: debe comenzar con http:// o https://"
            if not parsed.netloc:
                return False, "URL inválida: no contiene un dominio."

            resp = self.session.head(url, timeout=self.timeout, allow_redirects=True)
            if resp.status_code == 405:  # HEAD no permitido, probar GET
                resp = self.session.get(url, timeout=self.timeout, stream=True)
                resp.close()

            if resp.status_code == 200:
                return True, ""
            elif resp.status_code == 403:
                return False, f"Acceso denegado (403). El sitio bloquea scrapers externos."
            elif resp.status_code == 404:
                return False, f"Página no encontrada (404)."
            elif resp.status_code == 429:
                return False, f"Demasiadas solicitudes (429). El sitio limita el acceso."
            else:
                return False, f"Error HTTP {resp.status_code} al acceder a la URL."

        except requests.exceptions.ConnectionError:
            return False, "No se pudo conectar. Verifica que la URL sea correcta y que haya internet."
        except requests.exceptions.Timeout:
            return False, f"Timeout: el servidor no respondió en {self.timeout} segundos."
        except requests.exceptions.RequestException as e:
            return False, f"Error de red: {str(e)}"

    # ------------------------------------------------------------------
    def _fetch_page(self, url: str) -> Optional[BeautifulSoup]:
        """Descarga y parsea una página. Retorna None en error."""
        try:
            resp = self.session.get(url, timeout=self.timeout, allow_redirects=True)
            if resp.status_code != 200:
                return None
            # Solo procesar HTML
            ct = resp.headers.get("content-type", "")
            if "html" not in ct and "text" not in ct:
                return None
            resp.encoding = resp.apparent_encoding or "utf-8"
            return BeautifulSoup(resp.text, "lxml")
        except Exception:
            return None

    # ------------------------------------------------------------------
    def _extract_links(self, soup: BeautifulSoup, base_url: str, base_domain: str) -> List[str]:
        """Extrae enlaces internos válidos de una página."""
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith("javascript:") or href.startswith("mailto:"):
                continue
            absolute = urljoin(base_url, href)
            normalized = _normalize_url(absolute)
            if _same_domain(normalized, base_domain) and not _is_skippable(normalized):
                links.append(normalized)
        return links

    # ------------------------------------------------------------------
    def scrape(self, start_url: str) -> Generator[dict, None, None]:
        """
        Genera eventos de progreso + páginas scrapeadas.
        Yields dicts con 'type': 'progress' | 'page' | 'done' | 'error'.
        """
        start_url = _normalize_url(start_url)
        base_domain = urlparse(start_url).netloc

        visited: Set[str] = set()
        # Queue: (url, depth)
        queue: deque = deque()
        # Añadir con prioridad (se ordena primero)
        queue.append((start_url, 0, _priority_score(start_url)))

        pages_scraped = 0
        all_pages: List[PageData] = []

        yield {"type": "progress", "message": f"🔍 Iniciando scraping de {base_domain}..."}

        while queue and pages_scraped < self.max_pages:
            # Tomar la URL con mayor prioridad
            url, depth, priority = queue.popleft()

            if url in visited:
                continue
            if depth > self.max_depth:
                continue

            visited.add(url)

            yield {"type": "progress", "message": f"📄 Descargando página {pages_scraped + 1}: {url[:60]}..."}

            soup = self._fetch_page(url)
            if not soup:
                continue

            # Extraer datos
            title_el = soup.find("title") or soup.find("h1")
            title_text = title_el.get_text(strip=True) if title_el else url

            text = _extract_clean_text(soup)
            code_blocks = extract_code_blocks(soup, url, title_text)

            page = PageData(
                url=url,
                title=title_text,
                text_content=text,
                code_blocks=code_blocks,
                priority=priority,
            )
            all_pages.append(page)
            pages_scraped += 1

            yield {
                "type": "page",
                "url": url,
                "title": title_text,
                "code_count": len(code_blocks),
            }

            # Descubrir nuevos enlaces si no hemos llegado al límite de profundidad
            if depth < self.max_depth and pages_scraped < self.max_pages:
                new_links = self._extract_links(soup, url, base_domain)
                # Ordenar por prioridad (alta prioridad primero)
                scored = sorted(
                    [(l, depth + 1, _priority_score(l)) for l in new_links if l not in visited],
                    key=lambda x: x[2],
                    reverse=True,
                )
                for item in scored:
                    if item[0] not in visited:
                        queue.append(item)

            # Throttle educado
            time.sleep(0.3)

        yield {
            "type": "done",
            "pages": all_pages,
            "total_pages": pages_scraped,
            "total_code_blocks": sum(len(p.code_blocks) for p in all_pages),
        }
