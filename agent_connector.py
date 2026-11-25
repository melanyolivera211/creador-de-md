"""
agent_connector.py — Conector entre Agente-Scapper y MI-AGENTE.
Responsabilidad: escribir el Markdown generado en la bóveda de MI-AGENTE.

Estrategia de integración (sin modificar MI-AGENTE):
- El VaultParser de MI-AGENTE indexa automáticamente todos los .md en su raíz.
- El frontmatter esperado: aliases, tags, created, type, status, difficulty.
- La carpeta destino es '12-Proyectos' (para Library Skills) o una nueva '13-Library-Skills'.
- Al reiniciar MI-AGENTE, la nota queda disponible automáticamente en el Knowledge Graph.
"""

import re
import shutil
from datetime import date
from pathlib import Path
from typing import Tuple

from config import settings


class AgentConnector:
    """
    Conecta Agente-Scapper con MI-AGENTE escribiendo notas en su bóveda Obsidian.
    No modifica el código de MI-AGENTE. Solo escribe archivos .md.
    """

    def __init__(self, mi_agente_path: Path = None):
        self.mi_agente_root = Path(mi_agente_path or settings.mi_agente_path).resolve()

    # ------------------------------------------------------------------
    def _resolve_vault_path(self) -> Path:
        """
        Determina la ruta de destino dentro de MI-AGENTE.
        Usa '13-Library-Skills' (la crea si no existe).
        Alternativa: si no hay acceso, retorna None.
        """
        # Intentar primero con la carpeta específica para library skills
        target = self.mi_agente_root / "13-Library-Skills"
        try:
            target.mkdir(parents=True, exist_ok=True)
            return target
        except Exception:
            pass

        # Fallback: carpeta 12-Proyectos
        fallback = self.mi_agente_root / "12-Proyectos"
        if fallback.exists():
            return fallback

        return None

    # ------------------------------------------------------------------
    def is_available(self) -> bool:
        """Comprueba si MI-AGENTE es accesible."""
        return self.mi_agente_root.exists() and self.mi_agente_root.is_dir()

    # ------------------------------------------------------------------
    def get_status(self) -> dict:
        """Retorna el estado de la conexión con MI-AGENTE."""
        available = self.is_available()
        vault_path = self._resolve_vault_path() if available else None
        return {
            "available": available,
            "mi_agente_path": str(self.mi_agente_root),
            "target_folder": str(vault_path) if vault_path else None,
            "error": None if available else f"No se encontró MI-AGENTE en: {self.mi_agente_root}",
        }

    # ------------------------------------------------------------------
    def send_note(self, markdown_content: str, filename: str) -> Tuple[bool, str]:
        """
        Escribe el Markdown en la bóveda de MI-AGENTE.

        Args:
            markdown_content: Contenido completo del .md
            filename: Nombre del archivo (ej: "Ollama.md")

        Returns:
            (success: bool, message: str)
        """
        if not self.is_available():
            return False, (
                f"MI-AGENTE no encontrado en '{self.mi_agente_root}'. "
                "Verifica MI_AGENTE_PATH en el archivo .env"
            )

        vault_path = self._resolve_vault_path()
        if not vault_path:
            return False, "No se pudo crear/acceder al directorio de destino en MI-AGENTE."

        # Sanitizar nombre de archivo
        safe_name = re.sub(r"[<>:\"/\\|?*]", "", filename)
        if not safe_name.endswith(".md"):
            safe_name += ".md"

        dest_file = vault_path / safe_name

        # Si ya existe, crear versión con timestamp
        if dest_file.exists():
            stem = dest_file.stem
            today = date.today().isoformat()
            dest_file = vault_path / f"{stem}-{today}.md"

        try:
            dest_file.write_text(markdown_content, encoding="utf-8")
            return True, (
                f"✅ Nota enviada correctamente a MI-AGENTE.\n"
                f"Archivo: {dest_file.name}\n"
                f"Ubicación: {vault_path}\n\n"
                f"💡 La nota estará disponible en el Knowledge Graph la próxima vez "
                f"que MI-AGENTE se reinicie (el VaultParser la indexa automáticamente)."
            )
        except PermissionError:
            return False, f"Sin permiso para escribir en '{vault_path}'."
        except Exception as e:
            return False, f"Error al escribir el archivo: {str(e)}"
