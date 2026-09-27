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
    thinking: str = ""
    latency_ms: float
    model: str
    backend: Literal["ollama", "mock"]


class GeneratorUnavailable(Exception):
    """Raised when the local generator daemon cannot be contacted."""
    pass


class Generator(Protocol):
    def complete(self, prompt: str) -> Generation:
        ...

    def complete_stream(self, prompt: str):
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
            thinking_text = data.get("thinking", "")
            if not thinking_text and "<think>" in output_text and "</think>" in output_text:
                m = re.search(r"<think>(.*?)</think>", output_text, re.DOTALL)
                if m:
                    thinking_text = m.group(1).strip()
                    output_text = re.sub(r"<think>.*?</think>", "", output_text, flags=re.DOTALL).strip()
        except httpx.HTTPStatusError as e:
            try:
                err_detail = e.response.json().get("error", "")
            except Exception:
                err_detail = e.response.text
            installed = self.get_installed_models()
            avail_str = f" Available models: {', '.join(installed)}." if installed else ""
            if e.response.status_code == 404 or "not found" in err_detail.lower():
                raise GeneratorUnavailable(
                    f"Model '{self.model}' is not installed in local Ollama.{avail_str} Run 'ollama pull {self.model}' in terminal or select an installed model."
                ) from e
            raise GeneratorUnavailable(f"Ollama error for '{self.model}': {err_detail or e}") from e
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.NetworkError) as e:
            raise GeneratorUnavailable(
                f"Local Ollama daemon is not running at 127.0.0.1:11434. Start it with 'ollama serve'."
            ) from e
        except Exception as e:
            raise GeneratorUnavailable(
                f"Local generator error: {e}"
            ) from e

        lat_ms = (time.perf_counter() - t0) * 1000.0
        return Generation(
            text=output_text,
            thinking=thinking_text,
            latency_ms=lat_ms,
            model=self.model,
            backend="ollama",
        )

    def complete_stream(self, prompt: str):
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
            "keep_alive": "30m",
            "options": {"temperature": self.temperature},
        }
        try:
            with self.client.stream("POST", url, json=payload, timeout=self.timeout) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        import json
                        chunk = json.loads(line)
                        yield chunk
                    except Exception:
                        continue
        except httpx.HTTPStatusError as e:
            try:
                err_detail = e.response.json().get("error", "")
            except Exception:
                err_detail = e.response.text
            installed = self.get_installed_models()
            avail_str = f" Available models: {', '.join(installed)}." if installed else ""
            if e.response.status_code == 404 or "not found" in err_detail.lower():
                raise GeneratorUnavailable(
                    f"Model '{self.model}' is not installed in local Ollama.{avail_str} Run 'ollama pull {self.model}' in terminal or select an installed model."
                ) from e
            raise GeneratorUnavailable(f"Ollama error for '{self.model}': {err_detail or e}") from e
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.NetworkError) as e:
            raise GeneratorUnavailable(
                f"Local Ollama daemon is not running at 127.0.0.1:11434. Start it with 'ollama serve'."
            ) from e
        except Exception as e:
            raise GeneratorUnavailable(
                f"Local generator error: {e}"
            ) from e

    def get_installed_models(self) -> list[str]:
        try:
            resp = self.client.get(f"{self.base_url}/api/tags", timeout=2.0)
            if resp.status_code == 200:
                data = resp.json()
                return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
        except Exception:
            pass
        return []

    def is_model_installed(self, model_name: Optional[str] = None) -> bool:
        target = model_name or self.model
        installed = self.get_installed_models()
        if not installed:
            return False
        return any(
            target == inst or (":" in inst and target == inst.split(":")[0]) or (":" in target and target.split(":")[0] == inst)
            for inst in installed
        )

    def is_available(self) -> bool:
        return self.is_model_installed()


class MockGenerator:
    """Fast deterministic mock for tests without running an Ollama daemon."""

    def __init__(self, model: Optional[str] = None, config: Optional[SystemConfig] = None):
        if config is not None:
            self.model = config.system2_model
        else:
            self.model = model or "mock-offline-fast"

    def get_installed_models(self) -> list[str]:
        return ["mock-offline-fast"]

    def is_model_installed(self, model_name: Optional[str] = None) -> bool:
        return True

    def is_available(self) -> bool:
        return True

    def complete(self, prompt: str) -> Generation:
        t0 = time.perf_counter()

        p_low = prompt.lower()
        if "architecture decision" in p_low or "principal software architect" in p_low or "assigned adr number" in p_low:
            m_req = re.search(r'for the following requirement:\s*["\']?(.*?)["\']?\s*\n', prompt, re.IGNORECASE)
            req_text = m_req.group(1).strip() if m_req else "Enforce sovereign architectural policy"
            m_num = re.search(r'assigned adr number:\s*(adr-\d+)', prompt, re.IGNORECASE)
            adr_num = m_num.group(1).upper() if m_num else "ADR-046"
            title = req_text[:45].strip().title()
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            adr_md = (
                f"# {adr_num}: {title}\n\n"
                f"- Status: Accepted\n"
                f"- Date: {date_str}\n"
                f"- Supersedes: None\n"
                f"- Tags: architecture, standards, security\n\n"
                f"## Decision\n"
                f"Production code must strictly adhere to the following requirement: {req_text}.\n\n"
                f"## Required\n"
                f"- compliant_symbol\n\n"
                f"## Forbidden\n"
                f"- none\n"
            )
            return Generation(
                text=adr_md,
                thinking="Reasoning with local SLM on architectural requirements...\nExtracted policy constraints and formatted valid ADR.",
                latency_ms=(time.perf_counter() - t0) * 1000.0,
                model=self.model,
                backend="mock",
            )

        if "session_token" in p_low or ("session" in p_low and "token" in p_low) or "aegis_seal" in p_low:
            m_retries = re.search(r"must set retries=(\d+)", prompt) or re.search(r"retries=(\d+)", prompt)
            retries = int(m_retries.group(1)) if m_retries else 3
            m_timeout = re.search(r"must set timeout_s=([0-9.]+)", prompt) or re.search(r"timeout_s=([0-9.]+)", prompt)
            timeout_s = float(m_timeout.group(1).rstrip(".")) if m_timeout else 5.0

            if "rotate" in p_low:
                fn_name = "rotate_session_token"
            else:
                fn_name = "persist_session_token"

            code = (
                f"```python\n"
                f"def {fn_name}(token: str) -> str:\n"
                f'    return aegis_seal(token, key_id="kek-2026", timeout_s={timeout_s}, retries={retries})\n'
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
        thinking = "Analyzing leaf prompt constraints and active ADRs...\nConfirmed in-force policy ADR-014 (aegis_seal).\nEnsured deprecated methods (legacy_wrap) are excluded."
        return Generation(
            text=code,
            thinking=thinking,
            latency_ms=lat_ms,
            model=self.model,
            backend="mock",
        )

    def complete_stream(self, prompt: str):
        gen = self.complete(prompt)
        yield {
            "thinking": gen.thinking + "\n",
            "response": "",
            "done": False,
        }
        yield {
            "thinking": "",
            "response": gen.text,
            "done": True,
        }

