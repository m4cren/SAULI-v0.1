"""Backend-only environment settings. Missing credentials never become demo data."""

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supabase_url: str = ""
    supabase_secret_key: str = Field(default="", repr=False, exclude=True)
    supabase_storage_bucket: str = "sauli-item-images"
    ollama_host: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3.5:9b-q8_0"
    frontend_origin: str = "http://localhost:3000"
    app_timezone: str = "Asia/Manila"
    match_min_score: float = Field(default=45, ge=0, le=100)
    match_limit: int = Field(default=5, ge=1, le=20)
    deterministic_shortlist_limit: int = Field(default=10, ge=1, le=100)
    ai_rerank_limit: int = Field(default=5, ge=1, le=20)
    signed_url_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    max_image_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=25 * 1024 * 1024)

    @field_validator("ollama_host")
    @classmethod
    def normalize_ollama_client_host(cls, value: str) -> str:
        """Turn Ollama's common wildcard bind setting into a local client URL."""
        host = value.strip().rstrip("/")
        if not host.startswith(("http://", "https://")):
            host = "http://" + host
        host = host.replace("http://0.0.0.0", "http://127.0.0.1", 1)
        host = host.replace("https://0.0.0.0", "https://127.0.0.1", 1)
        return host


def get_settings() -> Settings:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
    values = {
        name: os.environ[name.upper()]
        for name in Settings.model_fields
        if name.upper() in os.environ
    }
    return Settings.model_validate(values)
