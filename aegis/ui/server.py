"""FastAPI Server for AegisTree Web Dashboard and Agent Review Gateway.
Binds to 127.0.0.1:8080 strictly, enforces local execution, and provides demo API endpoints.
"""

from __future__ import annotations
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from aegis.core.config import SystemConfig, config_manager
from aegis.core.ingestion import WorkspaceIngestor
from aegis.core.models import EpistemicStatus, NodeType
from aegis.demo import seed_vault
from aegis.mcp.tools import apply_patch, propose_patch, search_decisions
from aegis.system1.engine import EngineUnavailable
from aegis.system1.graph import MemoryGraph
from aegis.system1.leaf import compile_leaf, estimate_tokens, extract_function_source, select_function_name, select_target
from aegis.system1.router import Router
from aegis.system2.client import GeneratorUnavailable, MockGenerator, OllamaGenerator
from aegis.system2.prompt import compile_baseline, compute_unified_diff, extract_code, is_code_parseable


# Configuration verification
config = config_manager.config

# Enforce loopback rules at startup if ollama is configured
if config.system2_provider == "ollama":
    parsed_url = urlparse(config.ollama_base_url)
    if parsed_url.hostname not in ("127.0.0.1", "localhost"):
        raise RuntimeError(f"Web startup error: ollama_base_url host must be 127.0.0.1 or localhost, got '{parsed_url.hostname}'")

workspace_root = Path(config.workspace_root)
if not workspace_root.exists():
    seed_vault.write(workspace_root)

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

    return {
        "verdict_loaded": verdict_loaded,
        "verdict_error": verdict_error,
        "ollama_ok": ollama_ok,
        "model": config_manager.config.system2_model,
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
    # Restore demo_vault from seed constants
    seed_vault.write(workspace_root)

    # Re-initialize DB
    db_file = storage_dir / "memory.sqlite"
    for extra in ["", "-wal", "-shm"]:
        p = Path(f"{db_file}{extra}")
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass

    global graph, router
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
        baseline_data = {
            "text": base_gen.text,
            "code": base_code,
            "diff": base_diff,
            "latency_ms": base_gen.latency_ms,
            "unparseable": not base_parseable,
        }
    except GeneratorUnavailable:
        baseline_data = {
            "text": "Local generator is not running",
            "code": "",
            "diff": "",
            "latency_ms": 0.0,
            "unparseable": True,
        }

    try:
        aegis_gen = generator.complete(leaf_text)
        aegis_code = extract_code(aegis_gen.text)
        aegis_parseable = is_code_parseable(aegis_code, fn_name)
        aegis_diff = compute_unified_diff(old_fn_source, aegis_code) if aegis_parseable else ""
        aegis_data = {
            "text": aegis_gen.text,
            "code": aegis_code,
            "diff": aegis_diff,
            "latency_ms": aegis_gen.latency_ms,
            "unparseable": not aegis_parseable,
            "leaf": leaf_text,
        }
        tool_log.append({"tool": "propose_patch", "status": "ok"})
    except GeneratorUnavailable:
        aegis_data = {
            "text": "Local generator is not running",
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
        "baseline": baseline_data,
        "aegis": aegis_data,
        "tool_log": tool_log,
        "abstain_reason": None,
        "draft_adr": None,
    }


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
        {"id": n.id, "label": n.label, "type": n.type.value, "superseded_at": n.superseded_at.isoformat() if n.superseded_at else None}
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


# Mount static files at root
static_dir = Path(__file__).resolve().parent / "static"
static_dir.mkdir(parents=True, exist_ok=True)
index_file = static_dir / "index.html"
if not index_file.exists():
    index_file.write_text("<!DOCTYPE html><html><body>AegisTree</body></html>", encoding="utf-8")

app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
