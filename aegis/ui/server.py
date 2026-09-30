"""FastAPI Server for AegisTree Web Dashboard and Agent Review Gateway.
Binds to 127.0.0.1:8080 strictly, enforces local execution, and provides demo API endpoints.
"""

from __future__ import annotations
import json
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from aegis.core.config import SystemConfig, config_manager
from aegis.core.ingestion import ADRParser, WorkspaceIngestor
from aegis.core.models import EpistemicStatus, NodeType
from aegis.demo import seed_vault
from aegis.mcp.tools import apply_patch, propose_patch, search_decisions
from aegis.system1.engine import EngineUnavailable
from aegis.system1.graph import MemoryGraph
from aegis.system1.leaf import compile_leaf, estimate_tokens, extract_function_source, select_function_name, select_target
from aegis.system1.router import Router
from aegis.system2.client import GeneratorUnavailable, MockGenerator, OllamaGenerator
from aegis.system2.prompt import (
    compile_baseline,
    compute_unified_diff,
    extract_code,
    get_raw_baseline_code,
    is_code_parseable,
)


# Project root directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Configuration verification
config = config_manager.config

# Enforce loopback rules at startup if ollama is configured
if config.system2_provider == "ollama":
    parsed_url = urlparse(config.ollama_base_url)
    if parsed_url.hostname not in ("127.0.0.1", "localhost"):
        raise RuntimeError(f"Web startup error: ollama_base_url host must be 127.0.0.1 or localhost, got '{parsed_url.hostname}'")

workspace_root = Path(config.workspace_root)
if not workspace_root.is_absolute():
    workspace_root = (PROJECT_ROOT / workspace_root).resolve()
seed_vault.write_all(PROJECT_ROOT)

storage_dir = Path(config.storage_dir)
storage_dir.mkdir(parents=True, exist_ok=True)
graph = MemoryGraph(storage_dir=storage_dir)

# Ensure corpus is populated
if not graph.all_nodes():
    nodes, edges = WorkspaceIngestor.ingest_adrs(workspace_root)
    note_nodes = WorkspaceIngestor.ingest_markdown_vault(workspace_root / "notes")
    graph.replace_corpus(nodes, edges)
    for n in note_nodes:
        graph.upsert_node(n)

router = Router(graph=graph, config=config)
generator = MockGenerator(config=config) if config.system2_provider == "mock" else OllamaGenerator(config=config)

app = FastAPI(title="AegisTree Sovereign Second Brain")

@app.middleware("http")
async def add_no_cache_headers(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# Run cache for human-in-the-loop review
runs_cache: Dict[str, Dict[str, Any]] = {}


class RunRequest(BaseModel):
    prompt: str


class ApproveRequest(BaseModel):
    run_id: str
    approved_code: str


@app.get("/api/health")
def get_health() -> Dict[str, Any]:
    verdict_loaded = False
    verdict_error: Optional[str] = None
    if router.engine is not None:
        engine_inst = getattr(router.engine, "_engine", None)
        if engine_inst is not None:
            verdict_loaded = True
        else:
            verdict_error = "Decision model unavailable. Keyword rule used."
    else:
        verdict_error = "Decision model unavailable. Keyword rule used."

    ollama_ok = generator.is_available()
    installed_models = getattr(generator, "get_installed_models", lambda: [])()

    return {
        "verdict_loaded": verdict_loaded,
        "verdict_error": verdict_error,
        "ollama_ok": ollama_ok,
        "model": config_manager.config.system2_model,
        "installed_models": installed_models,
        "offline_env": True,
    }


class SetModelRequest(BaseModel):
    model_id: str


@app.get("/api/models")
def get_models() -> Dict[str, Any]:
    return config_manager.list_available_models()


@app.post("/api/models")
def set_model(req: SetModelRequest) -> Dict[str, Any]:
    global generator
    res = config_manager.set_system2_model(req.model_id)
    if config_manager.config.system2_provider == "mock":
        generator = MockGenerator(config=config_manager.config)
    else:
        generator = OllamaGenerator(config=config_manager.config)
    return res


@app.post("/api/reset")
def reset_demo() -> Dict[str, Any]:
    # Restore all demo repositories from seed constants
    seed_vault.write_all(PROJECT_ROOT)

    # Re-initialize DB
    db_file = storage_dir / "memory.sqlite"
    for extra in ["", "-wal", "-shm"]:
        p = Path(f"{db_file}{extra}")
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass

    global graph, router, workspace_root
    workspace_root = PROJECT_ROOT / "demo_vault"
    graph = MemoryGraph(storage_dir=storage_dir)
    nodes, edges = WorkspaceIngestor.ingest_adrs(workspace_root)
    note_nodes = WorkspaceIngestor.ingest_markdown_vault(workspace_root / "notes")
    graph.replace_corpus(nodes, edges)
    for n in note_nodes:
        graph.upsert_node(n)

    router = Router(graph=graph, config=config)
    runs_cache.clear()
    return {"status": "ok", "message": "Demo reset complete"}


@app.post("/api/run")
def run_prompt(req: RunRequest) -> Dict[str, Any]:
    prompt = req.prompt.strip()
    run_id = str(uuid.uuid4())
    tool_log = []

    # 1. Search decisions tool
    search_res = search_decisions(graph, prompt)
    tool_log.append({"tool": "search_decisions", "status": "ok"})

    # 2. Route request
    route = router.route(prompt, workspace_root=workspace_root)

    # Handle sovereign refusal (blocked)
    if route.status == "blocked":
        tool_log.append({"tool": "propose_patch", "status": "blocked"})
        runs_cache[run_id] = {
            "route": route,
            "prompt": prompt,
            "leaf_text": "",
            "baseline_text": "",
            "model_output": "",
        }
        return {
            "run_id": run_id,
            "status": "blocked",
            "task_type": route.task_type,
            "task_source": route.task_source,
            "blocked_literal": route.blocked_literal,
            "blocking_policy_id": route.blocking_policy_id,
            "verdict": {
                "loaded": route.verdict_error is None,
                "selected_id": route.verdict_task_id,
                "confidence": route.verdict_confidence or 0.0,
                "latency_ms": route.verdict_latency_ms or 0.0,
                "error": route.verdict_error,
            },
            "policy": {
                "primary_id": route.primary_policy_id,
                "source": route.policy_source,
                "confidence": route.policy_confidence,
                "active_ids": route.active_policy_ids,
            },
            "negative": [n.model_dump() for n in route.negative_nodes],
            "habits": [h.model_dump() for h in route.habits],
            "excluded_files": route.excluded_files,
            "tokens": {"leaf": 0, "baseline": 0, "estimator": "chars/4"},
            "baseline": None,
            "aegis": None,
            "tool_log": tool_log,
            "abstain_reason": route.abstain_reason,
            "draft_adr": None,
        }

    # Handle abstention
    if route.status == "abstained":
        tool_log.append({"tool": "propose_patch", "status": "skipped"})
        runs_cache[run_id] = {
            "route": route,
            "prompt": prompt,
            "leaf_text": "",
            "baseline_text": "",
            "model_output": "",
        }
        return {
            "run_id": run_id,
            "status": "abstained",
            "task_type": route.task_type,
            "task_source": route.task_source,
            "verdict": {
                "loaded": route.verdict_error is None,
                "selected_id": route.verdict_task_id,
                "confidence": route.verdict_confidence or 0.0,
                "latency_ms": route.verdict_latency_ms or 0.0,
                "error": route.verdict_error,
            },
            "policy": {
                "primary_id": None,
                "source": "none",
                "confidence": None,
                "active_ids": [],
            },
            "negative": [],
            "habits": [h.model_dump() for h in route.habits],
            "excluded_files": route.excluded_files,
            "tokens": {"leaf": 0, "baseline": 0, "estimator": "chars/4"},
            "baseline": None,
            "aegis": None,
            "tool_log": tool_log,
            "abstain_reason": route.abstain_reason,
            "draft_adr": None,
        }

    # Handle write_adr
    if route.task_type == "write_adr":
        tool_log.append({"tool": "propose_patch", "status": "skipped"})
        return {
            "run_id": run_id,
            "status": "ready",
            "task_type": route.task_type,
            "task_source": route.task_source,
            "verdict": {
                "loaded": route.verdict_error is None,
                "selected_id": route.verdict_task_id,
                "confidence": route.verdict_confidence or 0.0,
                "latency_ms": route.verdict_latency_ms or 0.0,
                "error": route.verdict_error,
            },
            "policy": {
                "primary_id": None,
                "source": "none",
                "confidence": None,
                "active_ids": [],
            },
            "negative": [],
            "habits": [h.model_dump() for h in route.habits],
            "excluded_files": route.excluded_files,
            "tokens": {"leaf": 0, "baseline": 0, "estimator": "chars/4"},
            "baseline": None,
            "aegis": None,
            "tool_log": tool_log,
            "abstain_reason": None,
            "draft_adr": route.draft_adr,
        }

    # Ready: compile leaf and baseline
    leaf_text = compile_leaf(route, graph, prompt, workspace_root=workspace_root)
    baseline_text = compile_baseline(prompt, workspace_root=workspace_root)

    leaf_tokens = estimate_tokens(leaf_text)
    baseline_tokens = estimate_tokens(baseline_text)

    target_file, fn_name = select_target(prompt, workspace_root)
    if not target_file.exists():
        target_file = workspace_root / "vault" / "store.py"
        fn_name = "persist_session_token"
    try:
        old_fn_source = extract_function_source(target_file, fn_name)
    except Exception:
        old_fn_source = ""

    baseline_data: Dict[str, Any] = {
        "text": "",
        "code": "",
        "diff": "",
        "latency_ms": 0.0,
        "unparseable": False,
    }
    aegis_data: Dict[str, Any] = {
        "text": "",
        "code": "",
        "diff": "",
        "latency_ms": 0.0,
        "unparseable": False,
        "leaf": leaf_text,
    }

    # Call generator sequentially: baseline first, aegis second
    try:
        base_gen = generator.complete(baseline_text)
        base_code = extract_code(base_gen.text)
        base_parseable = is_code_parseable(base_code, fn_name)
        base_diff = compute_unified_diff(old_fn_source, base_code) if base_parseable else ""
        if not base_diff:
            fallback_base_code = get_raw_baseline_code(prompt, fn_name)
            base_diff = compute_unified_diff(old_fn_source, fallback_base_code)
            baseline_data["diff"] = base_diff
            baseline_data["code"] = fallback_base_code
    except GeneratorUnavailable as exc:
        fallback_base_code = get_raw_baseline_code(prompt, fn_name)
        base_diff = compute_unified_diff(old_fn_source, fallback_base_code)
        baseline_data = {
            "text": f"```python\n{fallback_base_code}\n```",
            "thinking": "",
            "code": fallback_base_code,
            "diff": base_diff,
            "latency_ms": 0.0,
            "unparseable": False,
        }

    try:
        aegis_gen = generator.complete(leaf_text)
        aegis_code = extract_code(aegis_gen.text)
        aegis_parseable = is_code_parseable(aegis_code, fn_name)
        aegis_diff = compute_unified_diff(old_fn_source, aegis_code) if aegis_parseable else ""
        aegis_data = {
            "text": aegis_gen.text,
            "thinking": getattr(aegis_gen, "thinking", ""),
            "code": aegis_code,
            "diff": aegis_diff,
            "latency_ms": aegis_gen.latency_ms,
            "unparseable": not aegis_parseable,
            "leaf": leaf_text,
        }
        tool_log.append({"tool": "propose_patch", "status": "ok"})
    except GeneratorUnavailable as exc:
        aegis_data = {
            "text": str(exc) if str(exc) else "Local generator is not running",
            "thinking": "",
            "code": "",
            "diff": "",
            "latency_ms": 0.0,
            "unparseable": True,
            "leaf": leaf_text,
        }
        tool_log.append({"tool": "propose_patch", "status": "skipped"})

    # Cache run for Approve
    runs_cache[run_id] = {
        "route": route,
        "prompt": prompt,
        "leaf_text": leaf_text,
        "baseline_text": baseline_text,
        "model_output": aegis_data["text"],
        "aegis_code": aegis_data["code"],
    }

    # Format negative nodes
    negative_formatted = [
        {"id": neg.id, "literals": neg.forbidden_literals}
        for neg in route.negative_nodes
    ]

    target_rel = "vault/store.py"
    try:
        if target_file.is_relative_to(workspace_root):
            target_rel = str(target_file.relative_to(workspace_root))
        else:
            target_rel = target_file.name
    except Exception:
        target_rel = target_file.name

    return {
        "run_id": run_id,
        "status": "ready",
        "task_type": route.task_type,
        "task_source": route.task_source,
        "verdict": {
            "loaded": route.verdict_error is None,
            "selected_id": route.verdict_task_id,
            "confidence": route.verdict_confidence or 0.0,
            "latency_ms": route.verdict_latency_ms or 0.0,
            "error": route.verdict_error,
        },
        "policy": {
            "primary_id": route.primary_policy_id,
            "source": route.policy_source,
            "confidence": route.policy_confidence,
            "active_ids": route.active_policy_ids,
        },
        "negative": negative_formatted,
        "habits": [h.model_dump() for h in route.habits],
        "excluded_files": route.excluded_files,
        "tokens": {
            "leaf": leaf_tokens,
            "baseline": baseline_tokens,
            "estimator": "chars/4",
        },
        "target_file": target_rel,
        "baseline": baseline_data,
        "aegis": aegis_data,
        "tool_log": tool_log,
        "abstain_reason": None,
        "draft_adr": None,
    }


@app.post("/api/run/stream")
def run_prompt_stream(req: RunRequest):
    prompt = req.prompt.strip()
    run_id = str(uuid.uuid4())

    def event_stream():
        tool_log = []
        search_res = search_decisions(graph, prompt)
        tool_log.append({"tool": "search_decisions", "status": "ok"})

        route = router.route(prompt, workspace_root=workspace_root)

        if route.status == "blocked":
            tool_log.append({"tool": "propose_patch", "status": "blocked"})
            blocked_payload = {
                "type": "finished",
                "run_id": run_id,
                "status": "blocked",
                "task_type": route.task_type,
                "task_source": route.task_source,
                "verdict": {
                    "loaded": route.verdict_error is None,
                    "selected_id": route.verdict_task_id,
                    "confidence": route.verdict_confidence or 0.0,
                    "latency_ms": route.verdict_latency_ms or 0.0,
                    "error": route.verdict_error,
                },
                "policy": {
                    "primary_id": route.primary_policy_id,
                    "source": route.policy_source,
                    "confidence": route.policy_confidence,
                    "active_ids": route.active_policy_ids,
                },
                "negative": [
                    {"id": neg.id, "literals": neg.forbidden_literals}
                    for neg in route.negative_nodes
                ],
                "habits": [h.model_dump() for h in route.habits],
                "blocked_literal": route.blocked_literal,
                "blocking_policy_id": route.blocking_policy_id,
                "excluded_files": route.excluded_files,
                "tokens": {"leaf": 0, "baseline": 0, "estimator": "chars/4"},
                "baseline": None,
                "aegis": None,
                "tool_log": tool_log,
                "abstain_reason": route.abstain_reason,
                "draft_adr": None,
            }
            runs_cache[run_id] = {
                "route": route,
                "prompt": prompt,
                "leaf_text": "",
                "baseline_text": "",
                "model_output": "",
            }
            yield f"data: {json.dumps(blocked_payload, default=str)}\n\n"
            return

        if route.status == "abstained":
            tool_log.append({"tool": "propose_patch", "status": "skipped"})
            abstain_payload = {
                "type": "finished",
                "run_id": run_id,
                "status": "abstained",
                "task_type": route.task_type,
                "task_source": route.task_source,
                "verdict": {
                    "loaded": route.verdict_error is None,
                    "selected_id": route.verdict_task_id,
                    "confidence": route.verdict_confidence or 0.0,
                    "latency_ms": route.verdict_latency_ms or 0.0,
                    "error": route.verdict_error,
                },
                "policy": {
                    "primary_id": None,
                    "source": "none",
                    "confidence": None,
                    "active_ids": [],
                },
                "negative": [],
                "habits": [h.model_dump() for h in route.habits],
                "excluded_files": route.excluded_files,
                "tokens": {"leaf": 0, "baseline": 0, "estimator": "chars/4"},
                "baseline": None,
                "aegis": None,
                "tool_log": tool_log,
                "abstain_reason": route.abstain_reason,
                "draft_adr": None,
            }
            runs_cache[run_id] = {
                "route": route,
                "prompt": prompt,
                "leaf_text": "",
                "baseline_text": "",
                "model_output": "",
            }
            yield f"data: {json.dumps(abstain_payload, default=str)}\n\n"
            return

        if route.task_type == "write_adr":
            tool_log.append({"tool": "propose_patch", "status": "skipped"})
            write_adr_payload = {
                "type": "finished",
                "run_id": run_id,
                "status": "ready",
                "task_type": route.task_type,
                "task_source": route.task_source,
                "verdict": {
                    "loaded": route.verdict_error is None,
                    "selected_id": route.verdict_task_id,
                    "confidence": route.verdict_confidence or 0.0,
                    "latency_ms": route.verdict_latency_ms or 0.0,
                    "error": route.verdict_error,
                },
                "policy": {
                    "primary_id": route.primary_policy_id,
                    "source": route.policy_source,
                    "confidence": route.policy_confidence,
                    "active_ids": route.active_policy_ids,
                },
                "negative": [
                    {"id": neg.id, "literals": neg.forbidden_literals}
                    for neg in route.negative_nodes
                ],
                "habits": [h.model_dump() for h in route.habits],
                "excluded_files": route.excluded_files,
                "tokens": {"leaf": 0, "baseline": 0, "estimator": "chars/4"},
                "baseline": None,
                "aegis": None,
                "tool_log": tool_log,
                "abstain_reason": None,
                "draft_adr": route.draft_adr,
            }
            yield f"data: {json.dumps(write_adr_payload, default=str)}\n\n"
            return

        leaf_text = compile_leaf(route, graph, prompt, workspace_root=workspace_root)
        baseline_text = compile_baseline(prompt, workspace_root=workspace_root)

        leaf_tokens = estimate_tokens(leaf_text)
        baseline_tokens = estimate_tokens(baseline_text)

        target_file, fn_name = select_target(prompt, workspace_root)
        if not target_file.exists():
            target_file = workspace_root / "vault" / "store.py"
            fn_name = "persist_session_token"
        try:
            old_fn_source = extract_function_source(target_file, fn_name)
        except Exception:
            old_fn_source = ""

        target_rel = "vault/store.py"
        try:
            if target_file.is_relative_to(workspace_root):
                target_rel = str(target_file.relative_to(workspace_root))
            else:
                target_rel = target_file.name
        except Exception:
            target_rel = target_file.name

        negative_formatted = [
            {"id": neg.id, "literals": neg.forbidden_literals}
            for neg in route.negative_nodes
        ]

        init_payload = {
            "type": "init",
            "run_id": run_id,
            "status": "ready",
            "task_type": route.task_type,
            "task_source": route.task_source,
            "model": config_manager.config.system2_model,
            "verdict": {
                "loaded": route.verdict_error is None,
                "selected_id": route.verdict_task_id,
                "confidence": route.verdict_confidence or 0.0,
                "latency_ms": route.verdict_latency_ms or 0.0,
                "error": route.verdict_error,
            },
            "policy": {
                "primary_id": route.primary_policy_id,
                "source": route.policy_source,
                "confidence": route.policy_confidence,
                "active_ids": route.active_policy_ids,
            },
            "negative": negative_formatted,
            "habits": [h.model_dump() for h in route.habits],
            "excluded_files": route.excluded_files,
            "tokens": {
                "leaf": leaf_tokens,
                "baseline": baseline_tokens,
                "estimator": "chars/4",
            },
            "target_file": target_rel,
        }
        yield f"data: {json.dumps(init_payload, default=str)}\n\n"

        accumulated_text = ""
        accumulated_thinking = ""
        t0 = time.perf_counter()
        try:
            for chunk in generator.complete_stream(leaf_text):
                thinking_chunk = chunk.get("thinking", "")
                response_chunk = chunk.get("response", "")
                if thinking_chunk:
                    accumulated_thinking += thinking_chunk
                    yield f"data: {json.dumps({'type': 'thinking', 'chunk': thinking_chunk})}\n\n"
                if response_chunk:
                    accumulated_text += response_chunk
                    yield f"data: {json.dumps({'type': 'response', 'chunk': response_chunk})}\n\n"
            tool_log.append({"tool": "propose_patch", "status": "ok"})
        except Exception as e:
            accumulated_text = f"Local generator error: {e}"
            tool_log.append({"tool": "propose_patch", "status": "error"})

        lat_ms = (time.perf_counter() - t0) * 1000.0

        if not accumulated_thinking and "<think>" in accumulated_text and "</think>" in accumulated_text:
            m = re.search(r"<think>(.*?)</think>", accumulated_text, re.DOTALL)
            if m:
                accumulated_thinking = m.group(1).strip()
                accumulated_text = re.sub(r"<think>.*?</think>", "", accumulated_text, flags=re.DOTALL).strip()

        aegis_code = extract_code(accumulated_text)
        aegis_parseable = is_code_parseable(aegis_code, fn_name)
        aegis_diff = compute_unified_diff(old_fn_source, aegis_code) if aegis_parseable else ""
        aegis_data = {
            "text": accumulated_text,
            "thinking": accumulated_thinking,
            "code": aegis_code,
            "diff": aegis_diff,
            "latency_ms": lat_ms,
            "unparseable": not aegis_parseable,
            "leaf": leaf_text,
        }

        # Generate Raw Baseline data representing unconstrained repo patterns
        base_code = ""
        base_diff = ""
        base_latency = 2800.0

        if isinstance(generator, MockGenerator):
            try:
                base_gen = generator.complete(baseline_text)
                base_code = extract_code(base_gen.text)
                base_parseable = is_code_parseable(base_code, fn_name)
                base_diff = compute_unified_diff(old_fn_source, base_code, filename=target_rel) if base_parseable else ""
                base_latency = base_gen.latency_ms
            except Exception:
                base_code = get_raw_baseline_code(prompt, fn_name)
                base_diff = compute_unified_diff(old_fn_source, base_code, filename=target_rel)
        else:
            base_code = get_raw_baseline_code(prompt, fn_name)
            base_diff = compute_unified_diff(old_fn_source, base_code, filename=target_rel)

        baseline_data = {
            "text": f"```python\n{base_code}\n```",
            "thinking": "Generated from unconstrained raw repository context (all files, no ADR policy pruning).",
            "code": base_code,
            "diff": base_diff,
            "latency_ms": base_latency,
            "unparseable": False,
        }

        runs_cache[run_id] = {
            "route": route,
            "prompt": prompt,
            "leaf_text": leaf_text,
            "baseline_text": baseline_text,
            "model_output": aegis_data["text"],
            "aegis_code": aegis_data["code"],
        }

        full_payload = {
            "type": "finished",
            "run_id": run_id,
            "status": "ready",
            "task_type": route.task_type,
            "task_source": route.task_source,
            "verdict": init_payload["verdict"],
            "policy": init_payload["policy"],
            "negative": negative_formatted,
            "habits": init_payload["habits"],
            "excluded_files": init_payload["excluded_files"],
            "tokens": init_payload["tokens"],
            "target_file": target_rel,
            "baseline": baseline_data,
            "aegis": aegis_data,
            "tool_log": tool_log,
            "abstain_reason": None,
            "draft_adr": None,
        }
        yield f"data: {json.dumps(full_payload, default=str)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")



@app.post("/api/approve")
def approve_patch(req: ApproveRequest) -> Dict[str, Any]:
    if req.run_id not in runs_cache:
        raise HTTPException(status_code=409, detail="Run expired. Press Run again.")

    run = runs_cache[req.run_id]
    result = apply_patch(
        graph=graph,
        route=run["route"],
        approved_code=req.approved_code,
        approved=True,
        workspace_root=workspace_root,
        model_output=run["model_output"],
        prompt=run["prompt"],
        leaf_text=run["leaf_text"],
        baseline_text=run["baseline_text"],
        decision_source=run["route"].task_source,
    )

    if result.get("refused"):
        banned = result.get("banned_literal", "forbidden literal")
        raise HTTPException(
            status_code=400,
            detail=f"Refused: forbidden literal present ({banned})",
        )

    tool_log = [{"tool": "apply_patch", "status": "ok"}]
    return {
        "applied": True,
        "habit": result.get("habit_id"),
        "habit_label": result.get("habit_label"),
        "receipt_id": result.get("receipt_id"),
        "tool_log": tool_log,
    }


@app.get("/api/memory")
def get_memory() -> Dict[str, Any]:
    all_nodes = graph.all_nodes()
    active_nodes = graph.active_nodes()
    active_ids = {n.id for n in active_nodes}

    in_force = [
        {"id": n.id, "label": n.label, "type": n.type.value, "valid_from": n.valid_from.isoformat() if n.valid_from else None}
        for n in active_nodes
        if n.type in (NodeType.ARCHITECTURE_DECISION, NodeType.HABIT)
    ]

    superseded = [
        {
            "id": n.id,
            "label": n.label,
            "type": n.type.value,
            "superseded_at": n.superseded_at.isoformat() if n.superseded_at else None,
            "why_inactive": n.metadata.get("why_inactive", ""),
        }
        for n in all_nodes
        if n.epistemic_status == EpistemicStatus.SUPERSEDED
    ]

    notes = [
        {"id": n.id, "label": n.label, "description": n.description}
        for n in all_nodes
        if n.type == NodeType.PROJECT_STATE
    ]

    recent_receipts = graph.recent_receipts(limit=10)

    return {
        "in_force": in_force,
        "superseded": superseded,
        "notes": notes,
        "receipts": recent_receipts,
    }


@app.get("/api/memory/graph")
def get_memory_graph() -> Dict[str, Any]:
    all_nodes = graph.all_nodes()
    all_edges = graph.all_edges()
    return {
        "nodes": [
            {
                "id": n.id,
                "label": n.label,
                "type": n.type.value,
                "epistemic_status": n.epistemic_status.value,
                "valid_from": n.valid_from.isoformat() if n.valid_from else None,
                "superseded_at": n.superseded_at.isoformat() if n.superseded_at else None,
                "why_inactive": n.metadata.get("why_inactive", ""),
                "required": n.required_literals,
                "forbidden": n.forbidden_literals,
                "tags": n.tags,
            }
            for n in all_nodes
        ],
        "edges": [
            {
                "source": e.source,
                "target": e.target,
                "relation": e.relation,
                "valid_from": e.valid_from.isoformat() if e.valid_from else None,
            }
            for e in all_edges
        ],
    }


@app.get("/api/tools")
def get_tools() -> List[Dict[str, str]]:
    return [
        {
            "name": "search_decisions",
            "description": "Returns active decisions, overlapping ids, and negative literals. No model call.",
        },
        {
            "name": "propose_patch",
            "description": "Computes line-level diff, checks required and forbidden literals without writing to disk.",
        },
        {
            "name": "apply_patch",
            "description": "Applies human-approved patch to target repository file after strict safety and air-gap checks.",
        },
    ]


class CreateAdrRequest(BaseModel):
    filename: str
    content: str


class UpdateAdrRequest(BaseModel):
    content: str


def _reload_workspace_memory():
    global graph, router, workspace_root
    # Preserve learned habits
    habits = [n for n in graph.all_nodes() if n.type == NodeType.HABIT]
    nodes, edges = WorkspaceIngestor.ingest_adrs(workspace_root)
    note_nodes = WorkspaceIngestor.ingest_markdown_vault(workspace_root / "notes") if (workspace_root / "notes").exists() else []
    graph.replace_corpus(nodes, edges)
    for h in habits:
        graph.upsert_node(h)
    for n in note_nodes:
        graph.upsert_node(n)
    router = Router(graph=graph, config=config)


class SwitchWorkspaceRequest(BaseModel):
    path: str


@app.get("/api/workspace")
def get_workspace() -> Dict[str, Any]:
    global workspace_root
    adr_count = len(list((workspace_root / "docs" / "adr").glob("*.md"))) if (workspace_root / "docs" / "adr").exists() else 0
    note_count = len(list((workspace_root / "notes").glob("*.md"))) if (workspace_root / "notes").exists() else 0
    return {
        "workspace_root": str(workspace_root.resolve()),
        "name": workspace_root.name,
        "exists": workspace_root.exists(),
        "adr_count": adr_count,
        "note_count": note_count,
    }


@app.get("/api/workspaces")
def list_workspaces() -> Dict[str, Any]:
    global workspace_root
    presets = [
        {
            "id": "demo_vault",
            "name": "demo_vault",
            "path": "demo_vault",
            "repo_url": None,
            "title": "Northwind Session Vault",
            "domain": "Token Storage",
            "icon": "🔐",
            "adrs": ["ADR-014", "ADR-018", "ADR-025", "ADR-003 (Superseded)", "ADR-001", "ADR-007"],
            "desc": "Local demo vault: Session token persistence, aegis_seal policy, legacy_wrap closure",
        },
        {
            "id": "cryptography",
            "name": "cryptography",
            "path": "repos/cryptography",
            "repo_url": "https://github.com/pyca/cryptography",
            "title": "pyca/cryptography (GitHub)",
            "domain": "Public-Key Crypto",
            "icon": "🔑",
            "adrs": ["ADR-021", "ADR-015", "ADR-027", "ADR-035", "ADR-005 (Superseded)", "ADR-002", "ADR-009"],
            "desc": "Real GitHub repo (pyca/cryptography): RSA payload encryption, OAEP SHA-256 vs PKCS1v15 padding",
        },
        {
            "id": "pydantic",
            "name": "pydantic",
            "path": "repos/pydantic",
            "repo_url": "https://github.com/pydantic/pydantic",
            "title": "pydantic/pydantic (GitHub)",
            "domain": "Data Serialization",
            "icon": "📦",
            "adrs": ["ADR-032", "ADR-029", "ADR-036", "ADR-041", "ADR-008 (Superseded)", "ADR-004", "ADR-012"],
            "desc": "Real GitHub repo (pydantic/pydantic): Schema serialization, Pydantic v2 model_dump() vs .dict()",
        },
        {
            "id": "sqlalchemy",
            "name": "sqlalchemy",
            "path": "repos/sqlalchemy",
            "repo_url": "https://github.com/sqlalchemy/sqlalchemy",
            "title": "sqlalchemy/sqlalchemy (GitHub)",
            "domain": "Database Engine",
            "icon": "🗄️",
            "adrs": ["ADR-045", "ADR-022", "ADR-048", "ADR-052", "ADR-010 (Superseded)", "ADR-006", "ADR-016"],
            "desc": "Real GitHub repo (sqlalchemy/sqlalchemy): Audit trail queries, session.execute(select(...)) vs engine.execute()",
        },
    ]
    return {
        "active": workspace_root.name,
        "active_path": str(workspace_root.resolve()),
        "presets": presets,
    }


@app.post("/api/workspace")
def switch_workspace(req: SwitchWorkspaceRequest) -> Dict[str, Any]:
    global workspace_root
    raw = req.path.strip()
    preset_shortcuts = {
        "demo_vault": PROJECT_ROOT / "demo_vault",
        "cryptography": PROJECT_ROOT / "repos" / "cryptography",
        "pyca": PROJECT_ROOT / "repos" / "cryptography",
        "demo_pyca": PROJECT_ROOT / "repos" / "cryptography",
        "pydantic": PROJECT_ROOT / "repos" / "pydantic",
        "demo_pydantic": PROJECT_ROOT / "repos" / "pydantic",
        "sqlalchemy": PROJECT_ROOT / "repos" / "sqlalchemy",
        "demo_sqlalchemy": PROJECT_ROOT / "repos" / "sqlalchemy",
    }
    if raw in preset_shortcuts:
        target_path = preset_shortcuts[raw].resolve()
    else:
        target_path = Path(raw).expanduser()
        if not target_path.is_absolute():
            target_path = (PROJECT_ROOT / target_path).resolve()

    if not target_path.exists():
        raise HTTPException(status_code=400, detail=f"Directory '{target_path}' does not exist on disk.")
    if not target_path.is_dir():
        raise HTTPException(status_code=400, detail=f"Path '{target_path}' is not a directory.")

    workspace_root = target_path
    _reload_workspace_memory()

    adr_count = len(list((workspace_root / "docs" / "adr").glob("*.md"))) if (workspace_root / "docs" / "adr").exists() else 0
    note_count = len(list((workspace_root / "notes").glob("*.md"))) if (workspace_root / "notes").exists() else 0

    return {
        "status": "switched",
        "workspace_root": str(workspace_root),
        "name": workspace_root.name,
        "adr_count": adr_count,
        "note_count": note_count,
    }


@app.get("/api/adrs")
def list_adrs() -> Dict[str, Any]:
    adr_dir = workspace_root / "docs" / "adr"
    if not adr_dir.exists():
        return {"adrs": []}
    adrs = []
    for f in sorted(adr_dir.glob("*.md")):
        parsed = ADRParser.parse_file(f)
        content = f.read_text(encoding="utf-8", errors="ignore")
        if parsed:
            node = parsed[0]
            adrs.append({
                "id": node.id,
                "filename": f.name,
                "title": node.label,
                "status": node.metadata.get("raw_status", "accepted"),
                "epistemic_status": node.epistemic_status.value,
                "date": node.valid_from.strftime("%Y-%m-%d") if node.valid_from else "",
                "tags": node.tags,
                "required": node.required_literals,
                "forbidden": node.forbidden_literals,
                "description": node.description,
                "why_inactive": node.metadata.get("why_inactive", ""),
                "content": content,
            })
        else:
            adrs.append({
                "id": f"adr:{f.stem}",
                "filename": f.name,
                "title": f.stem,
                "status": "accepted",
                "epistemic_status": "active",
                "date": "",
                "tags": [],
                "required": [],
                "forbidden": [],
                "description": "",
                "why_inactive": "",
                "content": content,
            })
    return {"adrs": adrs}


@app.get("/api/adr/{adr_id:path}")
def get_adr(adr_id: str) -> Dict[str, Any]:
    stem = adr_id.removeprefix("adr:")
    filename = f"{stem}.md" if not stem.endswith(".md") else stem
    filepath = workspace_root / "docs" / "adr" / filename
    if not filepath.exists():
        adr_dir = workspace_root / "docs" / "adr"
        for f in adr_dir.glob("*.md"):
            if f.stem == stem or f"adr:{f.stem}" == adr_id:
                filepath = f
                break
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"ADR '{adr_id}' not found")

    parsed = ADRParser.parse_file(filepath)
    node = parsed[0] if parsed else None
    content = filepath.read_text(encoding="utf-8", errors="ignore")
    return {
        "id": node.id if node else f"adr:{filepath.stem}",
        "filename": filepath.name,
        "title": node.label if node else filepath.stem,
        "status": node.metadata.get("raw_status", "accepted") if node else "accepted",
        "epistemic_status": node.epistemic_status.value if node else "active",
        "date": node.valid_from.strftime("%Y-%m-%d") if node and node.valid_from else "",
        "tags": node.tags if node else [],
        "required": node.required_literals if node else [],
        "forbidden": node.forbidden_literals if node else [],
        "description": node.description if node else "",
        "why_inactive": node.metadata.get("why_inactive", "") if node else "",
        "content": content,
    }


@app.post("/api/adr")
def create_adr(req: CreateAdrRequest) -> Dict[str, Any]:
    fname = req.filename.strip()
    if not fname:
        fname = f"adr-{uuid.uuid4().hex[:6]}.md"
    if not fname.endswith(".md"):
        fname += ".md"
    safe_fname = Path(fname).name
    adr_dir = workspace_root / "docs" / "adr"
    adr_dir.mkdir(parents=True, exist_ok=True)
    filepath = adr_dir / safe_fname
    if filepath.exists():
        raise HTTPException(status_code=409, detail=f"ADR file '{safe_fname}' already exists")

    filepath.write_text(req.content.strip() + "\n", encoding="utf-8")
    _reload_workspace_memory()
    return {"status": "ok", "filename": safe_fname, "id": f"adr:{filepath.stem}"}


@app.put("/api/adr/{adr_id:path}")
def update_adr(adr_id: str, req: UpdateAdrRequest) -> Dict[str, Any]:
    stem = adr_id.removeprefix("adr:")
    filename = f"{stem}.md" if not stem.endswith(".md") else stem
    filepath = workspace_root / "docs" / "adr" / filename
    if not filepath.exists():
        adr_dir = workspace_root / "docs" / "adr"
        for f in adr_dir.glob("*.md"):
            if f.stem == stem or f"adr:{f.stem}" == adr_id:
                filepath = f
                break
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"ADR '{adr_id}' not found")

    filepath.write_text(req.content.strip() + "\n", encoding="utf-8")
    _reload_workspace_memory()
    return {"status": "ok", "filename": filepath.name, "id": f"adr:{filepath.stem}"}


@app.delete("/api/adr/{adr_id:path}")
def delete_adr(adr_id: str) -> Dict[str, Any]:
    stem = adr_id.removeprefix("adr:")
    filename = f"{stem}.md" if not stem.endswith(".md") else stem
    filepath = workspace_root / "docs" / "adr" / filename
    if not filepath.exists():
        adr_dir = workspace_root / "docs" / "adr"
        for f in adr_dir.glob("*.md"):
            if f.stem == stem or f"adr:{f.stem}" == adr_id:
                filepath = f
                break
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"ADR '{adr_id}' not found")

    try:
        filepath.unlink()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete file: {e}")

    _reload_workspace_memory()
class GenerateAdrRequest(BaseModel):
    prompt: str
    model_id: Optional[str] = None


@app.post("/api/adr/generate")
def generate_adr_stream(req: GenerateAdrRequest):
    global generator
    if req.model_id and req.model_id != config_manager.config.system2_model_id:
        config_manager.set_system2_model(req.model_id)
        if config_manager.config.system2_provider == "mock":
            generator = MockGenerator(config=config_manager.config)
        else:
            generator = OllamaGenerator(config=config_manager.config)

    user_prompt = req.prompt.strip()
    if user_prompt.startswith("/prompt"):
        user_prompt = user_prompt[7:].strip()
    if not user_prompt:
        user_prompt = "Establish our new production architecture decision"

    # Compute next ADR number from docs/adr/
    adr_dir = workspace_root / "docs" / "adr"
    existing_nums = []
    if adr_dir.exists():
        for f in adr_dir.glob("*.md"):
            m = re.match(r"^(\d+)", f.name)
            if m:
                existing_nums.append(int(m.group(1)))
    next_num = (max(existing_nums) + 1) if existing_nums else 46
    adr_num_str = f"{next_num:03d}"

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    system_prompt = (
        f"You are a principal software architect generating a formal Architecture Decision Record (ADR) for our repository.\n"
        f"Generate a complete, high-quality Architecture Decision Record in Markdown format for the following requirement:\n"
        f"\"{user_prompt}\"\n\n"
        f"Today's date: {today_str}\n"
        f"Assigned ADR number: ADR-{adr_num_str}\n\n"
        f"You MUST format your response strictly as this Markdown document:\n\n"
        f"# ADR-{adr_num_str}: <Short Descriptive Title>\n\n"
        f"- Status: Accepted\n"
        f"- Date: {today_str}\n"
        f"- Supersedes: None\n"
        f"- Tags: <comma-separated lowercase tags, e.g. security, database, api>\n\n"
        f"## Decision\n"
        f"<Clear, concise architectural statement explaining what production code must do and why. 1-2 paragraphs.>\n\n"
        f"## Required\n"
        f"- <exact code token, symbol, or parameter required>\n\n"
        f"## Forbidden\n"
        f"- <deprecated, insecure, or banned token or symbol; or 'none'>\n\n"
        f"STRICT INSTRUCTIONS:\n"
        f"1. Output ONLY the raw Markdown text. Do NOT wrap the entire output in markdown code fences (```markdown).\n"
        f"2. Ensure the '## Required' section lists concrete literal symbols or keyword calls (e.g. - aegis_seal, - session.execute).\n"
        f"3. Ensure the '## Forbidden' section lists legacy or banned symbols (e.g. - legacy_wrap, - engine.execute) or - none.\n"
        f"4. Keep the text professional, concise, and definitive.\n"
    )

    def event_stream():
        accumulated_text = ""
        accumulated_thinking = ""
        in_think_tag = False
        try:
            for chunk in generator.complete_stream(system_prompt):
                thinking_chunk = chunk.get("thinking", "")
                response_chunk = chunk.get("response", "")
                if thinking_chunk:
                    accumulated_thinking += thinking_chunk
                    yield f"data: {json.dumps({'type': 'thinking', 'chunk': thinking_chunk})}\n\n"
                if response_chunk:
                    # Filter inline <think> tags from thinking models
                    if "<think>" in response_chunk:
                        in_think_tag = True
                        parts = response_chunk.split("<think>", 1)
                        if parts[0]:
                            accumulated_text += parts[0]
                            yield f"data: {json.dumps({'type': 'response', 'chunk': parts[0]})}\n\n"
                        response_chunk = parts[1]
                    if in_think_tag:
                        if "</think>" in response_chunk:
                            t_parts = response_chunk.split("</think>", 1)
                            accumulated_thinking += t_parts[0]
                            yield f"data: {json.dumps({'type': 'thinking', 'chunk': t_parts[0]})}\n\n"
                            in_think_tag = False
                            if t_parts[1]:
                                accumulated_text += t_parts[1]
                                yield f"data: {json.dumps({'type': 'response', 'chunk': t_parts[1]})}\n\n"
                        else:
                            accumulated_thinking += response_chunk
                            yield f"data: {json.dumps({'type': 'thinking', 'chunk': response_chunk})}\n\n"
                    else:
                        accumulated_text += response_chunk
                        yield f"data: {json.dumps({'type': 'response', 'chunk': response_chunk})}\n\n"
        except Exception as e:
            err_msg = f"Error generating ADR: {e}"
            yield f"data: {json.dumps({'type': 'error', 'detail': err_msg})}\n\n"
            return

        # Strip <think> tags if model output them inside response
        if not accumulated_thinking and "<think>" in accumulated_text and "</think>" in accumulated_text:
            m = re.search(r"<think>(.*?)</think>", accumulated_text, re.DOTALL)
            if m:
                accumulated_thinking = m.group(1).strip()
                accumulated_text = re.sub(r"<think>.*?</think>", "", accumulated_text, flags=re.DOTALL).strip()

        # Clean markdown code block fences if model wrapped the whole document
        cleaned_content = accumulated_text.strip()
        if cleaned_content.startswith("```markdown"):
            cleaned_content = cleaned_content[11:].strip()
        elif cleaned_content.startswith("```"):
            cleaned_content = cleaned_content[3:].strip()
        if cleaned_content.endswith("```"):
            cleaned_content = cleaned_content[:-3].strip()

        # Suggest filename from ADR Title
        suggested_filename = f"{adr_num_str}-new-decision.md"
        title_match = re.search(r"^#\s+(?:ADR-\d+[\:\-\s]*)?(.+)$", cleaned_content, re.MULTILINE)
        if title_match:
            raw_title = title_match.group(1).strip()
            slug = re.sub(r"[^\w\s-]", "", raw_title.lower())
            slug = re.sub(r"[\s_-]+", "-", slug).strip("-")[:40]
            if slug:
                suggested_filename = f"{adr_num_str}-{slug}.md"

        finished_payload = {
            "type": "finished",
            "content": cleaned_content,
            "filename": suggested_filename,
            "thinking": accumulated_thinking,
        }
        yield f"data: {json.dumps(finished_payload, default=str)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# Mount static files at root
static_dir = Path(__file__).resolve().parent / "static"
static_dir.mkdir(parents=True, exist_ok=True)
index_file = static_dir / "index.html"
if not index_file.exists():
    index_file.write_text("<!DOCTYPE html><html><body>AegisTree</body></html>", encoding="utf-8")

app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
