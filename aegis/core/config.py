"""System Configuration & Model Registry for AegisTree.
Air-gapped configuration supporting strictly local System 1 and System 2 models.
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, Any, Optional
from pydantic import BaseModel


import httpx


DEFAULT_CONFIG_PATH = Path(".aegis/config.json")

SYSTEM2_CATALOG = {
    "qwen2.5-coder:7b": {
        "name": "Qwen 2.5 Coder 7B",
        "provider": "ollama",
        "params": "7.6B",
        "disk_size_gb": 4.7,
        "description": "High-capacity local model for >= 16 GB RAM workstations.",
        "context_window": 32768,
    },
    "deepseek-r1:8b": {
        "name": "DeepSeek R1 8B",
        "provider": "ollama",
        "params": "8.0B",
        "disk_size_gb": 4.9,
        "description": "Reasoning model distilled into Llama 3.1 architecture.",
        "context_window": 32768,
    },
    "deepseek-r1:14b": {
        "name": "DeepSeek R1 14B",
        "provider": "ollama",
        "params": "14.7B",
        "disk_size_gb": 9.0,
        "description": "High-capacity reasoning model for large architectural tasks.",
        "context_window": 32768,
    },
    "mock-offline-fast": {
        "name": "Lightweight Mock Engine",
        "provider": "mock",
        "params": "0B",
        "disk_size_gb": 0.0,
        "description": "Instant in-process dry-run engine for low-storage / test runs.",
        "context_window": 32768,
    },
}


class SystemConfig(BaseModel):
    system1_engine: str = "verdict_v1.4"
    system1_confidence_threshold: float = 0.5
    # Revival checks below this stay unblocked; output-side literal checks still apply
    system1_revival_threshold: float = 0.7
    # Verdict policy retrieval: pick must clear this to lead over token overlap
    system1_retrieval_threshold: float = 0.5
    # Revival block when retrieval itself landed on the superseded decision
    system1_revival_assist_threshold: float = 0.5
    # Web search (No-workspace mode only, opt-in per conversation). Set False to
    # guarantee no request ever leaves the machine, e.g. before a demo.
    allow_web_search: bool = True
    web_search_timeout_s: float = 4.0
    # Optional self-hosted SearXNG, tried before DuckDuckGo and Wikipedia
    web_search_searxng_url: Optional[str] = None
    system2_model: str = "qwen2.5-coder:3b"
    system2_provider: str = "ollama"  # web startup rejects "mock"
    ollama_base_url: str = "http://127.0.0.1:11434"
    system2_temperature: float = 0.1
    system2_timeout_seconds: float = 120.0
    workspace_root: str = "demo_vault"
    storage_dir: str = ".aegis"
    demo_port: int = 8080


class ConfigManager:
    """Manages reading and writing AegisTree configuration dynamically."""

    def __init__(self, config_path: Path = DEFAULT_CONFIG_PATH):
        self.config_path = config_path
        self._config: Optional[SystemConfig] = None
        self.load()

    def load(self) -> SystemConfig:
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._config = SystemConfig(**data)
            except Exception:
                self._config = SystemConfig()
        else:
            self._config = SystemConfig()
            self.save()
        return self._config

    def save(self) -> None:
        if self._config is None:
            self._config = SystemConfig()
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self._config.model_dump(), f, indent=2)

    @property
    def config(self) -> SystemConfig:
        if self._config is None:
            self.load()
        return self._config

    def _query_installed_models(self) -> list[str]:
        try:
            with httpx.Client(timeout=2.0, trust_env=False) as client:
                r = client.get(f"{self.config.ollama_base_url}/api/tags")
                if r.status_code == 200:
                    return [m.get("name", "") for m in r.json().get("models", []) if m.get("name")]
        except Exception:
            pass
        return []

    def set_system2_model(self, model_id: str) -> Dict[str, Any]:
        """Switches the active System 2 generative model."""
        installed = self._query_installed_models()
        is_installed = any(
            model_id == inst or (":" in inst and model_id == inst.split(":")[0]) or (":" in model_id and model_id.split(":")[0] == inst)
            for inst in installed
        )

        if model_id not in SYSTEM2_CATALOG:
            entry = {
                "name": model_id,
                "provider": "ollama",
                "params": "Custom",
                "disk_size_gb": 0.0,
                "description": "User-specified custom local model.",
                "installed": is_installed,
            }
        else:
            entry = dict(SYSTEM2_CATALOG[model_id])
            entry["installed"] = is_installed if entry.get("provider") != "mock" else True

        self.config.system2_model = model_id
        self.config.system2_provider = entry.get("provider", "ollama")
        self.save()
        return {
            "status": "success",
            "active_model": model_id,
            "installed": entry["installed"],
            "metadata": entry,
        }

    def list_available_models(self) -> Dict[str, Any]:
        catalog = {}
        for mid, info in SYSTEM2_CATALOG.items():
            if info.get("provider") == "mock":
                continue
            catalog[mid] = {
                "name": info["name"],
                "provider": info["provider"],
            }

        return {
            "active_model": self.config.system2_model,
            "models": catalog,
        }


# Global singleton instance
config_manager = ConfigManager()
