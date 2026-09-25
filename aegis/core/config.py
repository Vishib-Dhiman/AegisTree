"""System Configuration & Model Registry for AegisTree.
Air-gapped configuration supporting strictly local System 1 and System 2 models.
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, Any, Optional
from pydantic import BaseModel


DEFAULT_CONFIG_PATH = Path(".aegis/config.json")

SYSTEM2_CATALOG = {
    "qwen2.5-coder:3b": {
        "name": "Qwen 2.5 Coder 3B",
        "provider": "ollama",
        "params": "3.1B",
        "disk_size_gb": 1.9,
        "description": "Recommended default. Lightweight, fast, air-gapped sovereign model.",
        "context_window": 32768,
    },
    "qwen2.5-coder:7b": {
        "name": "Qwen 2.5 Coder 7B",
        "provider": "ollama",
        "params": "7.6B",
        "disk_size_gb": 4.7,
        "description": "High-capacity local model for >= 16 GB RAM workstations.",
        "context_window": 32768,
    },
    "deepseek-r1:7b": {
        "name": "DeepSeek R1 Distill Qwen 7B",
        "provider": "ollama",
        "params": "7.6B",
        "disk_size_gb": 4.7,
        "description": "Chain-of-thought architectural reasoning for complex refactoring.",
        "context_window": 32768,
    },
    "deepseek-r1:8b": {
        "name": "DeepSeek R1 Distill Llama 8B",
        "provider": "ollama",
        "params": "8.0B",
        "disk_size_gb": 4.9,
        "description": "Reasoning model distilled into Llama 3.1 architecture.",
        "context_window": 32768,
    },
    "deepseek-r1:14b": {
        "name": "DeepSeek R1 Distill Qwen 14B",
        "provider": "ollama",
        "params": "14.7B",
        "disk_size_gb": 9.0,
        "description": "High-capacity reasoning model for large architectural tasks.",
        "context_window": 32768,
    },
    "llama3.1:8b": {
        "name": "Llama 3.1 8B Instruct",
        "provider": "ollama",
        "params": "8.0B",
        "disk_size_gb": 4.9,
        "description": "Generalist open-weights baseline instruction model.",
        "context_window": 8192,
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
    system1_confidence_threshold: float = 0.55
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

    def set_system2_model(self, model_id: str) -> Dict[str, Any]:
        """Switches the active System 2 generative model."""
        if model_id not in SYSTEM2_CATALOG:
            entry = {
                "name": model_id,
                "provider": "ollama",
                "params": "Custom",
                "disk_size_gb": 0.0,
                "description": "User-specified custom local model.",
            }
        else:
            entry = SYSTEM2_CATALOG[model_id]

        self.config.system2_model = model_id
        self.config.system2_provider = entry.get("provider", "ollama")
        self.save()
        return {
            "status": "success",
            "active_model": model_id,
            "metadata": entry,
        }

    def list_available_models(self) -> Dict[str, Any]:
        return {
            "active_model": self.config.system2_model,
            "models": SYSTEM2_CATALOG,
        }


# Global singleton instance
config_manager = ConfigManager()
