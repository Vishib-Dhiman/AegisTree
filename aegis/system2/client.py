"""System 2 Generative Model Client for AegisTree.
Implements strictly air-gapped Ollama communication with loopback validation and trust_env=False.
"""

from __future__ import annotations
import re
import time
from typing import Literal, Optional, Protocol
from urllib.parse import urlparse
import httpx
from pydantic import BaseModel

from aegis.core.config import SystemConfig


class Generation(BaseModel):
    text: str
    latency_ms: float
    model: str
    backend: Literal["ollama", "mock"]


class GeneratorUnavailable(Exception):
    """Raised when the local generator daemon cannot be contacted."""
    pass


class Generator(Protocol):
    def complete(self, prompt: str) -> Generation:
        ...


class OllamaGenerator:
    """Air-gapped client for local Ollama daemon."""

    def __init__(self, config: Optional[SystemConfig] = None):
        self.config = config or SystemConfig()
        self.base_url = self.config.ollama_base_url.rstrip("/")
        self.model = self.config.system2_model
        self.timeout = self.config.system2_timeout_seconds
        self.temperature = self.config.system2_temperature

        # Loopback validation
        parsed = urlparse(self.base_url)
        host = parsed.hostname
        if host not in ("127.0.0.1", "localhost"):
            raise ValueError(
                f"Air-gap violation: Ollama base URL host must be 127.0.0.1 or localhost, got '{host}'"
            )

        # httpx client with trust_env=False to ignore environment proxies
        self.client = httpx.Client(
            trust_env=False,
            timeout=self.timeout,
            follow_redirects=False,
        )

    def complete(self, prompt: str) -> Generation:
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": "30m",
            "options": {"temperature": self.temperature},
        }

        t0 = time.perf_counter()
        try:
            resp = self.client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            output_text = data.get("response", "")
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.NetworkError) as e:
            raise GeneratorUnavailable(
                f"Local generator is not running at 127.0.0.1:11434 ({e})"
            ) from e
        except Exception as e:
            raise GeneratorUnavailable(
                f"Local generator error at 127.0.0.1:11434 ({e})"
            ) from e

        lat_ms = (time.perf_counter() - t0) * 1000.0
        return Generation(
            text=output_text,
            latency_ms=lat_ms,
            model=self.model,
            backend="ollama",
        )

    def is_available(self) -> bool:
        try:
            resp = self.client.get(f"{self.base_url}/api/tags", timeout=2.0)
            return resp.status_code == 200
        except Exception:
            return False


class MockGenerator:
    """Fast deterministic mock for tests without running an Ollama daemon."""

    def __init__(self, model: Optional[str] = None, config: Optional[SystemConfig] = None):
        if config is not None:
            self.model = config.system2_model
        else:
            self.model = model or "mock-offline-fast"

    def is_available(self) -> bool:
        return True

    def complete(self, prompt: str) -> Generation:
        t0 = time.perf_counter()

        p_low = prompt.lower()
        if "session_token" in p_low or ("session" in p_low and "token" in p_low) or "aegis_seal" in p_low:
            retries = 1 if "retries=1" in prompt else 3
            if "rotate" in p_low:
                fn_name = "rotate_session_token"
            else:
                fn_name = "persist_session_token"

            code = (
                f"```python\n"
                f"def {fn_name}(token: str) -> str:\n"
                f'    return aegis_seal(token, key_id="kek-2026", timeout_s=5.0, retries={retries})\n'
                f"```"
            )
        elif "oaep" in p_low or "rsa" in p_low or "encrypt" in p_low:
            code = (
                "```python\n"
                "def encrypt_rsa_payload(public_key, plaintext: bytes) -> bytes:\n"
                "    return public_key.encrypt(\n"
                "        plaintext,\n"
                "        padding.OAEP(\n"
                "            mgf=padding.MGF1(hashes.SHA256()),\n"
                "            algorithm=hashes.SHA256(),\n"
                "            label=None\n"
                "        )\n"
                "    )\n"
                "```"
            )
        elif "pydantic" in p_low or "serialize" in p_low or "model_dump" in p_low:
            code = (
                "```python\n"
                "def serialize_vault_payload(model) -> dict:\n"
                "    return model.model_dump()\n"
                "```"
            )
        elif "sqlalchemy" in p_low or "database" in p_low or "audit" in p_low:
            code = (
                "```python\n"
                "def query_audit_trail(session, user_id: str):\n"
                "    stmt = select(AuditLog).where(AuditLog.user_id == user_id)\n"
                "    return session.execute(stmt).scalars().all()\n"
                "```"
            )
        else:
            code = (
                f"```python\n"
                f"def persist_session_token(token: str) -> str:\n"
                f'    return aegis_seal(token, key_id="kek-2026", timeout_s=5.0, retries=3)\n'
                f"```"
            )

        lat_ms = (time.perf_counter() - t0) * 1000.0
        return Generation(
            text=code,
            latency_ms=lat_ms,
            model=self.model,
            backend="mock",
        )
