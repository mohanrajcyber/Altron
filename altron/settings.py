from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Harvested option names from LiteLLM + quantum-free-router."""

    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    nvidia_nim_api_key: str = ""
    nvidia_nim_api_key_2: str = ""
    nvidia_nim_api_key_3: str = ""
    nvidia_nim_api_base: str = "https://integrate.api.nvidia.com/v1"
    altron_model: str = "nvidia/nemotron-3-super-120b-a12b"
    altron_fallback_model: str = "nvidia/nemotron-3-super-120b-a12b"
    altron_host: str = "127.0.0.1"
    altron_port: int = 8088
    altron_data_dir: Path = Field(default=ROOT / "data")
    altron_workspace: Path = Field(default=ROOT)
    altron_timeout_seconds: float = 90.0
    altron_max_retries: int = 1
    ollama_base_url: str = "http://127.0.0.1:11434/v1"
    ollama_model: str = "llama3.2:1b"
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    qdrant_url: str = "http://127.0.0.1:6333"
    e2b_api_key: str = ""
    n8n_webhook_url: str = ""
    n8n_base_url: str = "http://127.0.0.1:5678"
    comfyui_url: str = "http://127.0.0.1:8188"
    altron_browser_headless: bool = False
    altron_browser_allowlist: str = ""
    altron_ide_port: int = 8443
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_from: str = ""

    @property
    def api_keys(self) -> list[str]:
        keys = [
            self.nvidia_nim_api_key.strip(),
            self.nvidia_nim_api_key_2.strip(),
            self.nvidia_nim_api_key_3.strip(),
        ]
        return [k for k in keys if k]

    @property
    def memory_path(self) -> Path:
        return self.altron_data_dir / "memory.jsonl"

    @property
    def identity_path(self) -> Path:
        return self.altron_data_dir / "identity.json"

    @property
    def jobs_path(self) -> Path:
        return self.altron_data_dir / "jobs.jsonl"

    @property
    def sandbox_path(self) -> Path:
        return self.altron_data_dir / "sandbox"

    @property
    def traces_path(self) -> Path:
        return self.altron_data_dir / "traces.jsonl"

    @property
    def vectors_path(self) -> Path:
        return self.altron_data_dir / "vectors.jsonl"

    @property
    def graph_path(self) -> Path:
        return self.altron_data_dir / "graph.json"

    @property
    def intent_path(self) -> Path:
        return self.altron_data_dir / "intent.json"

    @property
    def safety_path(self) -> Path:
        return self.altron_data_dir / "safety_pending.json"

    @property
    def browser_allowlist(self) -> list[str]:
        raw = (self.altron_browser_allowlist or "").strip()
        if not raw:
            return []
        return [p.strip() for p in raw.split(",") if p.strip()]

    @property
    def has_think_backend(self) -> bool:
        return bool(self.api_keys)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
