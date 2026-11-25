# Agente-Scapper

## Extractor de Conocimiento Técnico desde Documentación

> **ELECTIVA II** — Proyecto académico  
> Convierte documentación de librerías en conocimiento práctico reutilizable.

---

## Idea central

```
URL DE DOCUMENTACIÓN
        ↓
SCRAPING CONTROLADO
        ↓
EXTRACCIÓN DE CÓDIGO + APIs
        ↓
ANÁLISIS CON GEMINI IA
        ↓
MÍNIMO 3 CASOS DE USO
        ↓
SCRIPTS MINIMALISTAS
        ↓
MARKDOWN ESTRUCTURADO (Library Skill)
        ↓
       ┌─────────────────┐
       ↓                 ↓
DESCARGAR .MD    ENVIAR A MI-AGENTE
```

---

## Stack

| Componente | Tecnología |
|---|---|
| Backend | FastAPI + Uvicorn |
| Scraping | requests + BeautifulSoup4 + lxml |
| IA | Google Gemini (gemini-1.5-flash) |
| Frontend | HTML + CSS + JavaScript (sin frameworks) |
| Knowledge Graph | MI-AGENTE (Obsidian Vault) |

---

## Estructura

```
Agente-Scapper/
├── app.py                  # Entry point: FastAPI + SSE + static files
├── config.py               # Configuración centralizada (Pydantic Settings)
├── scraper.py              # Scraper controlado (BFS, respeta dominio, evita duplicados)
├── extractor.py            # Extractor de código estructurado
├── analyzer.py             # Agente Gemini → 3+ casos de uso fundamentados
├── markdown_generator.py   # Generador de .md compatible Obsidian
├── agent_connector.py      # Conector con MI-AGENTE (escribe en su Vault)
├── requirements.txt
├── .env                    # Tu configuración local
├── .env.example            # Plantilla
├── README.md
└── frontend/
    └── index.html          # Interfaz web completa (todo embebido)
```

---

## Instalación rápida

```bash
# 1. Ir a la carpeta
cd "ELECTIVA II/Agente-Scapper"

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Configurar API Key
# Edita .env y reemplaza tu_api_key_aqui con tu clave de Google AI Studio
# https://aistudio.google.com/

# 4. Iniciar
python app.py
```

La aplicación abre en: **http://127.0.0.1:8000**

---

## Configuración (.env)

| Variable | Descripción | Default |
|---|---|---|
| `GOOGLE_API_KEY` | API Key de Google AI Studio | *(requerida)* |
| `GEMINI_MODEL` | Modelo de Gemini | `gemini-1.5-flash` |
| `MAX_PAGES` | Máximo de páginas a scrapear | `30` |
| `MAX_DEPTH` | Profundidad máxima del scraper | `3` |
| `REQUEST_TIMEOUT` | Timeout HTTP en segundos | `10` |
| `MIN_USE_CASES` | Mínimo de casos de uso | `3` |
| `HOST` | Host del servidor | `127.0.0.1` |
| `PORT` | Puerto del servidor | `8000` |
| `MI_AGENTE_PATH` | Ruta relativa a MI-AGENTE | `../MI-AGENTE` |

---

## Integración con MI-AGENTE

El botón **"Enviar a MI-AGENTE"** escribe el Markdown generado en:
```
MI-AGENTE/13-Library-Skills/[NombreLibrería].md
```

El VaultParser de MI-AGENTE indexa automáticamente todos los `.md` de su directorio al reiniciar.
El archivo queda disponible en el Knowledge Graph sin modificar código de MI-AGENTE.

---

## Endpoints API

| Endpoint | Método | Descripción |
|---|---|---|
| `/` | GET | Interfaz web |
| `/api/health` | GET | Estado del servidor |
| `/api/analyze` | POST | Pipeline completo (SSE) |
| `/api/export-markdown` | POST | Retorna el .md |
| `/api/send-to-agent` | POST | Envía a MI-AGENTE |

---

## Flujos de usuario

**Flujo principal:**
```
URL → Analizar → Resultado → Descargar .md → Revisar → Enviar a MI-AGENTE
```

**Solo descarga:**
```
URL → Analizar → Resultado → Descargar .md
```

**Nueva URL sin reiniciar:**
```
Resultado → "Nueva URL" → Nueva URL → Analizar → Nuevo resultado
```
