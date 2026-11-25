"""
config.py — Configuración centralizada del Agente-Scapper.
Usa Pydantic Settings para cargar desde .env y validar parámetros.
"""

from pathlib import Path
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración global del Agente-Scapper."""

    # Google AI
    google_api_key: Optional[str] = Field(default=None, alias="GOOGLE_API_KEY")
    gemini_model: str = Field(default="gemini-3.6-flash", alias="GEMINI_MODEL")

    # Scraping
    max_pages: int = Field(default=30, alias="MAX_PAGES")
    max_depth: int = Field(default=3, alias="MAX_DEPTH")
    request_timeout: int = Field(default=10, alias="REQUEST_TIMEOUT")

    # Análisis
    min_use_cases: int = Field(default=3, alias="MIN_USE_CASES")

    # Servidor
    host: str = Field(default="127.0.0.1", alias="HOST")
    port: int = Field(default=8000, alias="PORT")

    # Integración con MI-AGENTE
    mi_agente_path: Path = Field(
        default=Path("../MI-AGENTE"),
        alias="MI_AGENTE_PATH"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )


# Instancia singleton
settings = Settings()
