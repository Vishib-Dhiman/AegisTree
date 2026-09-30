"""FastAPI Server for AegisTree Web Dashboard and Agent Review Gateway.
Binds to 127.0.0.1:8080 strictly, enforces local execution, and provides demo API endpoints.
"""

from __future__ import annotations
import json
import os
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from aegis.core.config import SystemConfig, config_manager
from aegis.core.ingestion import ADRParser, WorkspaceIngestor
from aegis.core.watcher import WorkspaceWatcher
from aegis.core.models import EpistemicStatus, NodeType
from aegis.demo import seed_vault
from aegis.mcp.tools import apply_patch, propose_patch, search_decisions
from aegis.system1.engine import EngineUnavailable
from aegis.system1.graph import MemoryGraph
from aegis.system1.leaf import compile_leaf, estimate_tokens, extract_function_source, select_function_name, select_target
from aegis.system1.router import Router, scoped_exclusions
from aegis.system2.client import GeneratorUnavailable, MockGenerator, OllamaGenerator
from aegis.system2.websearch import SearchOutcome, WebSearcher, format_for_prompt
from aegis.system2.computer import MAX_TOOL_ROUNDS, computer_system_prompt, parse_tool_call, run_tool
from aegis.system2.images import normalize_images, screenshot_note
from clearsky.auth import (
    Auth,
    AuthStore,
    Mailer,
    OtpService,
    SessionManager,
    SmtpSettings,
    build_auth_router,
    load_or_create_secret,
)
from clearsky.auth.routes import public_user
from clearsky.workspace_memory import WorkspaceMemory
from aegis.system2.prompt import (
    compile_baseline,
    build_free_messages,
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

DEFAULT_WORKSPACE = Path(config.workspace_root)
if not DEFAULT_WORKSPACE.is_absolute():
    DEFAULT_WORKSPACE = (PROJECT_ROOT / DEFAULT_WORKSPACE).resolve()

# "No workspace" mode: requests go straight to the local model with no ADRs,
# bans, abstention or habits, and nothing is written to disk.
FREE_MODE_KEYS = {"__free__", "none", "free", "no_workspace"}
FREE_MODE_NAME = "No workspace"
# Create missing seed files only; resets (/api/reset, demo.sh) do the full rewrite
seed_vault.write_missing(PROJECT_ROOT)

storage_dir = Path(config.storage_dir)
storage_dir.mkdir(parents=True, exist_ok=True)

# One memory graph + router per workspace (users can be in different ones at
# once); habits from the old single memory.sqlite are carried over on first open
memory = WorkspaceMemory(storage_dir / "workspaces", config, legacy_storage=storage_dir)
memory.get(DEFAULT_WORKSPACE)
generator = MockGenerator(config=config) if config.system2_provider == "mock" else OllamaGenerator(config=config)

# ---- Multi-user: email one-time-code sign-in ----
auth_store = AuthStore(storage_dir / "auth.sqlite")
auth = Auth(
    store=auth_store,
    otp=OtpService(auth_store, load_or_create_secret(storage_dir / "secret.key")),
    mailer=Mailer(SmtpSettings.from_env(), storage_dir / "outbox.log"),
    sessions=SessionManager(auth_store),
    secure_cookies=config.https or os.environ.get("CLEARSKY_HTTPS") == "1",
)

PRESET_WORKSPACES = {
    "demo_vault": PROJECT_ROOT / "demo_vault",
    "cryptography": PROJECT_ROOT / "repos" / "cryptography",
    "pyca": PROJECT_ROOT / "repos" / "cryptography",
    "demo_pyca": PROJECT_ROOT / "repos" / "cryptography",
    "pydantic": PROJECT_ROOT / "repos" / "pydantic",
    "demo_pydantic": PROJECT_ROOT / "repos" / "pydantic",
    "sqlalchemy": PROJECT_ROOT / "repos" / "sqlalchemy",
    "demo_sqlalchemy": PROJECT_ROOT / "repos" / "sqlalchemy",
}


def _allowed_roots() -> List[Path]:
    extra = [(PROJECT_ROOT / r).resolve() if not Path(r).is_absolute() else Path(r).resolve()
             for r in config_manager.config.allowed_workspace_roots]
    return sorted({p.resolve() for p in PRESET_WORKSPACES.values()} | {DEFAULT_WORKSPACE.resolve()} | set(extra))


def _resolve_workspace(raw: str) -> Path:
    """A workspace a user may open: a preset, or inside an allowed root. Anything else is refused."""
    raw = raw.strip()
    if raw in PRESET_WORKSPACES:
        return PRESET_WORKSPACES[raw].resolve()
    target = Path(raw).expanduser()
    target = (target if target.is_absolute() else PROJECT_ROOT / target).resolve()
    if not any(target == allowed or target.is_relative_to(allowed) for allowed in _allowed_roots()):
        raise HTTPException(
            status_code=403,
            detail="That folder isn't an allowed workspace. Add it to allowed_workspace_roots in .aegis/config.json.",
        )
    return target


@dataclass
class UserState:
    root: Path
    free: bool = False


user_states: Dict[int, UserState] = {}
_state_lock = threading.Lock()


def _user_state(user: Dict[str, Any]) -> UserState:
    """Each signed-in user's workspace choice, restored from their last session."""
    with _state_lock:
        state = user_states.get(user["id"])
        if state is None:
            state = UserState(DEFAULT_WORKSPACE)
            last = user.get("last_workspace")
            if last == "__free__":
                state.free = True
            elif last:
                try:
                    candidate = _resolve_workspace(last)
                    if candidate.is_dir():
                        state.root = candidate
                except HTTPException:
                    pass
            user_states[user["id"]] = state
        return state


def _current_user(request: Request) -> Dict[str, Any]:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Not signed in")
    return user


def _bind(request: Request):
    """(workspace_root, graph, router, free_mode) for the signed-in user of this request."""
    state = _user_state(_current_user(request))
    handle = memory.get(state.root)
    return handle.root, handle.graph, handle.router, state.free


def _audit(request: Request, action: str, detail: Any = None) -> None:
    user = getattr(request.state, "user", None)
    auth_store.audit(user["id"] if user else None, action, detail)


_in_flight: set = set()
_in_flight_lock = threading.Lock()


def _claim_run(user_id: int) -> None:
    """One generation per user at a time, so nobody monopolises the local model."""
    with _in_flight_lock:
        if user_id in _in_flight:
            raise HTTPException(status_code=429, detail="You already have a request running. Wait for it to finish.")
        _in_flight.add(user_id)


def _release_run(user_id: int) -> None:
    with _in_flight_lock:
        _in_flight.discard(user_id)


def _released_after(stream, user_id: int):
    try:
        yield from stream
    finally:
        _release_run(user_id)

app = FastAPI(title="ClearSky")
app.include_router(build_auth_router(auth))

PUBLIC_API_PREFIXES = ("/api/auth/",)
APP_PAGES = {"/", "/index.html"}
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@app.middleware("http")
async def clearsky_sign_in(request: Request, call_next):
    """Every API call needs a session (except sign-in itself); the app page
    sends signed-out visitors to /login.html; cross-site writes are refused."""
    path = request.url.path
    if request.method in UNSAFE_METHODS and path.startswith("/api/"):
        origin = request.headers.get("origin")
        # Behind a tunnel the public hostname arrives as X-Forwarded-Host
        hosts = {request.headers.get("host"), request.headers.get("x-forwarded-host")} - {None}
        if origin and urlparse(origin).netloc not in hosts:
            return JSONResponse({"detail": "Cross-site request refused"}, status_code=403)
    user = auth.user_for(request)
    request.state.user = user
    if path.startswith("/api/") and not path.startswith(PUBLIC_API_PREFIXES) and user is None:
        return JSONResponse({"detail": "Not signed in"}, status_code=401)
    if path in APP_PAGES and user is None:
        return RedirectResponse("/login.html", status_code=303)
    return await call_next(request)


@app.middleware("http")
async def add_no_cache_headers(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# Run cache for human-in-the-loop review
runs_cache: Dict[str, Dict[str, Any]] = {}


class ChatTurn(BaseModel):
    role: str
    content: str


class RunRequest(BaseModel):
    prompt: str
    # Earlier turns of this chat thread, oldest first. Used in No-workspace mode;
    # governed runs stay single-shot so the leaf context stays minimal.
    history: List[ChatTurn] = []
    # Search the web for this turn (No-workspace mode only; ignored for governed runs)
    web_search: bool = False
    # Let the model use read-only tools on this machine (No-workspace mode only)
    computer: bool = False
    # Screenshots for this turn, base64 or data URLs (validated by normalize_images)
    images: List[str] = []


class ApproveRequest(BaseModel):
    run_id: str
    approved_code: str


@app.get("/api/health")
def get_health() -> Dict[str, Any]:
    verdict_loaded = False
    verdict_error: Optional[str] = None
    if memory.engine is not None:
        engine_inst = getattr(memory.engine, "_engine", None)
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
        "web_search_allowed": config_manager.config.allow_web_search,
        "computer_access_allowed": config_manager.config.allow_computer_access,
        "vision_model": config_manager.config.vision_model,
        "vision_available": _vision_available(),
    }


class SetModelRequest(BaseModel):
    model_id: str


@app.get("/api/models")
def get_models() -> Dict[str, Any]:
    return config_manager.list_available_models()


@app.post("/api/models")
def set_model(req: SetModelRequest, request: Request) -> Dict[str, Any]:
    global generator
    res = config_manager.set_system2_model(req.model_id)
    _audit(request, "model_switch", {"model": req.model_id})
    if config_manager.config.system2_provider == "mock":
        generator = MockGenerator(config=config_manager.config)
    else:
        generator = OllamaGenerator(config=config_manager.config)
    return res


@app.post("/api/reset")
def reset_demo(request: Request) -> Dict[str, Any]:
    """Restore the demo repositories and clear their memory. Affects every user."""
    seed_vault.write_all(PROJECT_ROOT)
    for root in {p.resolve() for p in PRESET_WORKSPACES.values()}:
        memory.forget(root, delete_storage=True)
    memory.get(DEFAULT_WORKSPACE)

    state = _user_state(_current_user(request))
    state.root, state.free = DEFAULT_WORKSPACE, False
    auth_store.set_last_workspace(_current_user(request)["id"], str(DEFAULT_WORKSPACE))
    runs_cache.clear()
    _audit(request, "demo_reset")
    return {"status": "ok", "message": "Demo reset complete"}


def _free_payload(run_id: str, text: str, thinking: str, lat_ms: float, error: bool) -> Dict[str, Any]:
    if not thinking and "<think>" in text and "</think>" in text:
        m = re.search(r"<think>(.*?)</think>", text, re.DOTALL)
        if m:
            thinking = m.group(1).strip()
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    return {
        "type": "finished",
        "run_id": run_id,
        "status": "free",
        "task_type": "free",
        "task_source": "none",
        "model": config_manager.config.system2_model,
        "workspace": None,
        "aegis": {
            "text": text,
            "thinking": thinking,
            "code": extract_code(text),
            "latency_ms": lat_ms,
            "error": error,
        },
        "tool_log": [{"tool": "generate", "status": "error" if error else "ok"}],
    }


def _web_search(query: str) -> SearchOutcome:
    cfg = config_manager.config
    if not cfg.allow_web_search:
        return SearchOutcome("disabled", error="allow_web_search is false in .aegis/config.json")
    searcher = WebSearcher(timeout_s=cfg.web_search_timeout_s, searxng_url=cfg.web_search_searxng_url)
    return searcher.search(query)


def _vision_available() -> bool:
    cfg = config_manager.config
    if isinstance(generator, MockGenerator):
        return True
    if not generator.is_model_installed(cfg.vision_model):
        return False
    return generator.supports_vision(cfg.vision_model)


def _generator_for(images: List[str]):
    """The generator for this turn: the active one, or the vision model when it can't read images.

    Returns (generator, model_name, vision_routed).
    """
    active = config_manager.config.system2_model
    if not images or isinstance(generator, MockGenerator) or generator.supports_vision():
        return generator, active, False
    vision_model = config_manager.config.vision_model
    turn_config = config_manager.config.model_copy(update={"system2_model": vision_model})
    return OllamaGenerator(config=turn_config), vision_model, True


def _checked_images(req: "RunRequest") -> List[str]:
    try:
        return normalize_images(req.images)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


# Headers added by tunnels and reverse proxies (cloudflared, nginx, ...). Their
# requests arrive from 127.0.0.1 but come from someone else's machine.
PROXY_HEADERS = ("cf-connecting-ip", "cf-ray", "x-forwarded-for", "x-real-ip", "forwarded")


def _is_local(request: Optional[Request]) -> bool:
    """True when the request comes from this machine (computer access is never offered to others)."""
    if request is None or request.client is None:
        return False
    if any(h in request.headers for h in PROXY_HEADERS):
        return False
    return request.client.host in LOOPBACK_HOSTS


def _sse(obj: Dict[str, Any]) -> str:
    return f"data: {json.dumps(obj, default=str)}\n\n"


def _free_stream(
    run_id: str,
    prompt: str,
    history: List[ChatTurn],
    web_search: bool = False,
    computer: bool = False,
    local: bool = False,
    images: Optional[List[str]] = None,
):
    """No-workspace generation, yielding the same SSE event types as a governed run.

    With computer access on, the model may call read-only tools (see
    aegis.system2.computer). Each round streams normally; when a round ends in a
    tool call, the tool runs, a 'tool' event is sent, and the model continues
    with the result, up to MAX_TOOL_ROUNDS calls.
    """
    history_dicts = [t.model_dump() for t in history]
    turns = len(build_free_messages(prompt, history_dicts)) - 2

    computer_status = "off"
    if computer:
        if not config_manager.config.allow_computer_access:
            computer_status = "disabled"
        elif not local:
            computer_status = "remote"
        else:
            computer_status = "on"
    computer_on = computer_status == "on"
    images = images or []
    turn_gen, turn_model, vision_routed = _generator_for(images)

    yield _sse({
        "type": "init", "run_id": run_id, "status": "free", "free": True, "history_turns": turns,
        "web_search": web_search, "computer": computer_status, "model": turn_model,
        "images": len(images), "vision_routed": vision_routed,
    })

    web: Dict[str, Any] = {"requested": web_search}
    web_context = None
    if web_search:
        yield _sse({"type": "search", "status": "searching"})
        outcome = _web_search(prompt)
        web.update(outcome.to_dict())
        web_context = format_for_prompt(outcome)
        yield _sse({"type": "search", "status": outcome.status, "provider": outcome.provider, "count": len(outcome.results)})

    extra = computer_system_prompt() if computer_on else None
    messages = build_free_messages(prompt, history_dicts, web_context, extra)
    if images:
        messages[-1]["images"] = images
    text, thinking, error = "", "", False
    tools: List[Dict[str, Any]] = []
    t0 = time.perf_counter()
    try:
        for round_idx in range(MAX_TOOL_ROUNDS + 1):
            round_text = ""
            call = None
            tools_left = computer_on and round_idx < MAX_TOOL_ROUNDS
            stream = turn_gen.chat_stream(messages)
            try:
                for chunk in stream:
                    if chunk.get("thinking"):
                        thinking += chunk["thinking"]
                        yield _sse({"type": "thinking", "chunk": chunk["thinking"]})
                    if chunk.get("response"):
                        round_text += chunk["response"]
                        yield _sse({"type": "response", "chunk": chunk["response"]})
                        # Stop as soon as a complete call arrives, before the model invents its result
                        if tools_left and ("<tool>" in round_text or round_text.lstrip().startswith(("{", "```"))):
                            call = parse_tool_call(round_text)
                            if call:
                                break
            finally:
                close = getattr(stream, "close", None)
                if close:
                    close()
            if tools_left and not call:
                call = parse_tool_call(round_text)
            if not call:
                text = round_text
                break
            tool_id = f"t{round_idx + 1}"
            yield _sse({"type": "tool", "id": tool_id, "status": "running", "name": call["name"], "args": call.get("args") or {}})
            result = run_tool(call)
            record = {"id": tool_id, **result.to_dict()}
            tools.append(record)
            yield _sse({"type": "tool", "status": "done", **record})
            messages = messages + [
                {"role": "assistant", "content": round_text},
                {"role": "user", "content": (
                    f"TOOL RESULT for {result.name} {json.dumps(result.args)}:\n{result.for_model()}\n\n"
                    "Call another tool if you still need information, otherwise answer my original question."
                )},
            ]
        else:
            text = round_text
    except Exception as e:
        text, error = f"Local generator error: {e}", True
    payload = _free_payload(run_id, text, thinking, (time.perf_counter() - t0) * 1000.0, error)
    payload["model"] = turn_model
    payload["images"] = len(images)
    payload["vision_routed"] = vision_routed
    payload["history_turns"] = turns
    payload["web"] = web
    payload["computer"] = {"status": computer_status, "tools": tools}
    if tools:
        payload["tool_log"] = [{"tool": t["name"], "status": "ok" if t["ok"] else "error"} for t in tools] + payload["tool_log"]
    yield _sse(payload)


@app.post("/api/run")
def run_prompt(req: RunRequest, request: Request) -> Dict[str, Any]:
    owner = _current_user(request)["id"]
    workspace_root, graph, router, free_mode = _bind(request)
    _claim_run(owner)
    try:
        return _run_prompt(req, request, owner, workspace_root, graph, router, free_mode)
    finally:
        _release_run(owner)


def _run_prompt(req: RunRequest, request: Request, owner: int, workspace_root: Path,
                graph: MemoryGraph, router: Router, free_mode: bool) -> Dict[str, Any]:
    prompt = req.prompt.strip()
    run_id = str(uuid.uuid4())
    tool_log = []
    images = _checked_images(req)

    if free_mode:
        # Same path as streaming, collected into one response
        payload: Dict[str, Any] = {}
        for event in _free_stream(run_id, prompt, req.history, req.web_search, req.computer, _is_local(request), images):
            evt = json.loads(event[len("data: "):])
            if evt.get("type") == "finished":
                payload = evt
        return payload

    # 1. Search decisions tool
    search_res = search_decisions(graph, prompt)
    tool_log.append({"tool": "search_decisions", "status": "ok"})

    # 2. Route request
    route = router.route(prompt, workspace_root=workspace_root)

    # Handle sovereign refusal (blocked)
    if route.status == "blocked":
        tool_log.append({"tool": "propose_patch", "status": "blocked"})
        runs_cache[run_id] = {
            "owner": owner,
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
            "block_method": route.block_method,
            "block_confidence": route.block_confidence,
            "revived_policy_id": route.revived_policy_id,
            "block_reason": route.abstain_reason,
            "verdict": {
                "loaded": route.verdict_error is None,
                "selected_id": route.verdict_task_id,
                "confidence": route.verdict_confidence or 0.0,
                "latency_ms": route.verdict_latency_ms or 0.0,
                "error": route.verdict_error,
                "threshold": config.system1_confidence_threshold,
                "system1_ms": route.system1_latency_ms,
            },
            "policy": {
                "primary_id": route.primary_policy_id,
                "source": route.policy_source,
                "confidence": route.policy_confidence,
                "active_ids": route.active_policy_ids,
                "retrieval": {
                    "source": route.retrieval_source,
                    "pick": route.retrieval_pick,
                    "confidence": route.retrieval_confidence,
                    "latency_ms": route.retrieval_latency_ms,
                    "scores": route.retrieval_scores,
                },
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
            "owner": owner,
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
                "threshold": config.system1_confidence_threshold,
                "system1_ms": route.system1_latency_ms,
            },
            "policy": {
                "primary_id": None,
                "source": "none",
                "confidence": None,
                "active_ids": [],
                "retrieval": {
                    "source": route.retrieval_source,
                    "pick": route.retrieval_pick,
                    "confidence": route.retrieval_confidence,
                    "latency_ms": route.retrieval_latency_ms,
                    "scores": route.retrieval_scores,
                },
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
                "threshold": config.system1_confidence_threshold,
                "system1_ms": route.system1_latency_ms,
            },
            "policy": {
                "primary_id": None,
                "source": "none",
                "confidence": None,
                "active_ids": [],
                "retrieval": {
                    "source": route.retrieval_source,
                    "pick": route.retrieval_pick,
                    "confidence": route.retrieval_confidence,
                    "latency_ms": route.retrieval_latency_ms,
                    "scores": route.retrieval_scores,
                },
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
        "source": "model",
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
        if base_diff:
            baseline_data.update(text=base_gen.text, code=base_code, diff=base_diff, latency_ms=base_gen.latency_ms)
        else:
            fallback_base_code = get_raw_baseline_code(prompt, fn_name)
            base_diff = compute_unified_diff(old_fn_source, fallback_base_code)
            baseline_data.update(diff=base_diff, code=fallback_base_code, latency_ms=None, source="template",
                                 thinking="Illustrative legacy pattern from this workspace's superseded decisions; not a model run.")
    except GeneratorUnavailable as exc:
        fallback_base_code = get_raw_baseline_code(prompt, fn_name)
        base_diff = compute_unified_diff(old_fn_source, fallback_base_code)
        baseline_data = {
            "text": f"```python\n{fallback_base_code}\n```",
            "thinking": "Illustrative legacy pattern from this workspace's superseded decisions; not a model run.",
            "code": fallback_base_code,
            "diff": base_diff,
            "latency_ms": None,
            "unparseable": False,
            "source": "template",
        }

    try:
        turn_gen, _, _ = _generator_for(images)
        aegis_gen = turn_gen.complete(
            f"{leaf_text}\n\n{screenshot_note(len(images))}" if images else leaf_text,
            images or None,
        )
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
            "owner": owner,
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
            "threshold": config.system1_confidence_threshold,
            "system1_ms": route.system1_latency_ms,
        },
        "policy": {
            "primary_id": route.primary_policy_id,
            "source": route.policy_source,
            "confidence": route.policy_confidence,
            "active_ids": route.active_policy_ids,
            "retrieval": {
                "source": route.retrieval_source,
                "pick": route.retrieval_pick,
                "confidence": route.retrieval_confidence,
                "latency_ms": route.retrieval_latency_ms,
                "scores": route.retrieval_scores,
            },
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
def run_prompt_stream(req: RunRequest, request: Request):
    prompt = req.prompt.strip()
    run_id = str(uuid.uuid4())
    images = _checked_images(req)
    owner = _current_user(request)["id"]
    workspace_root, graph, router, free_mode = _bind(request)
    _claim_run(owner)

    if free_mode:
        return StreamingResponse(
            _released_after(
                _free_stream(run_id, prompt, req.history, req.web_search, req.computer, _is_local(request), images),
                owner,
            ),
            media_type="text/event-stream",
        )

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
                    "threshold": config.system1_confidence_threshold,
                    "system1_ms": route.system1_latency_ms,
                },
                "policy": {
                    "primary_id": route.primary_policy_id,
                    "source": route.policy_source,
                    "confidence": route.policy_confidence,
                    "active_ids": route.active_policy_ids,
                    "retrieval": {
                        "source": route.retrieval_source,
                        "pick": route.retrieval_pick,
                        "confidence": route.retrieval_confidence,
                        "latency_ms": route.retrieval_latency_ms,
                        "scores": route.retrieval_scores,
                    },
                },
                "negative": [
                    {"id": neg.id, "literals": neg.forbidden_literals}
                    for neg in route.negative_nodes
                ],
                "habits": [h.model_dump() for h in route.habits],
                "blocked_literal": route.blocked_literal,
                "blocking_policy_id": route.blocking_policy_id,
                "block_method": route.block_method,
                "block_confidence": route.block_confidence,
                "revived_policy_id": route.revived_policy_id,
                "block_reason": route.abstain_reason,
                "excluded_files": route.excluded_files,
                "tokens": {"leaf": 0, "baseline": 0, "estimator": "chars/4"},
                "baseline": None,
                "aegis": None,
                "tool_log": tool_log,
                "abstain_reason": route.abstain_reason,
                "draft_adr": None,
            }
            runs_cache[run_id] = {
            "owner": owner,
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
                    "threshold": config.system1_confidence_threshold,
                    "system1_ms": route.system1_latency_ms,
                },
                "policy": {
                    "primary_id": None,
                    "source": "none",
                    "confidence": None,
                    "active_ids": [],
                    "retrieval": {
                        "source": route.retrieval_source,
                        "pick": route.retrieval_pick,
                        "confidence": route.retrieval_confidence,
                        "latency_ms": route.retrieval_latency_ms,
                        "scores": route.retrieval_scores,
                    },
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
            "owner": owner,
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
                    "threshold": config.system1_confidence_threshold,
                    "system1_ms": route.system1_latency_ms,
                },
                "policy": {
                    "primary_id": route.primary_policy_id,
                    "source": route.policy_source,
                    "confidence": route.policy_confidence,
                    "active_ids": route.active_policy_ids,
                    "retrieval": {
                        "source": route.retrieval_source,
                        "pick": route.retrieval_pick,
                        "confidence": route.retrieval_confidence,
                        "latency_ms": route.retrieval_latency_ms,
                        "scores": route.retrieval_scores,
                    },
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

        turn_gen, turn_model, vision_routed = _generator_for(images)
        init_payload = {
            "type": "init",
            "run_id": run_id,
            "status": "ready",
            "task_type": route.task_type,
            "task_source": route.task_source,
            "model": turn_model,
            "images": len(images),
            "vision_routed": vision_routed,
            "verdict": {
                "loaded": route.verdict_error is None,
                "selected_id": route.verdict_task_id,
                "confidence": route.verdict_confidence or 0.0,
                "latency_ms": route.verdict_latency_ms or 0.0,
                "error": route.verdict_error,
                "threshold": config.system1_confidence_threshold,
                "system1_ms": route.system1_latency_ms,
            },
            "policy": {
                "primary_id": route.primary_policy_id,
                "source": route.policy_source,
                "confidence": route.policy_confidence,
                "active_ids": route.active_policy_ids,
                "retrieval": {
                    "source": route.retrieval_source,
                    "pick": route.retrieval_pick,
                    "confidence": route.retrieval_confidence,
                    "latency_ms": route.retrieval_latency_ms,
                    "scores": route.retrieval_scores,
                },
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
            leaf_prompt = f"{leaf_text}\n\n{screenshot_note(len(images))}" if images else leaf_text
            for chunk in turn_gen.complete_stream(leaf_prompt, images or None):
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
        base_latency: Optional[float] = None
        base_source = "template"

        if isinstance(generator, MockGenerator):
            try:
                base_gen = generator.complete(baseline_text)
                base_code = extract_code(base_gen.text)
                base_parseable = is_code_parseable(base_code, fn_name)
                base_diff = compute_unified_diff(old_fn_source, base_code, filename=target_rel) if base_parseable else ""
                if base_diff:
                    base_latency, base_source = base_gen.latency_ms, "model"
            except Exception:
                base_diff = ""
        if not base_diff:
            base_code = get_raw_baseline_code(prompt, fn_name)
            base_diff = compute_unified_diff(old_fn_source, base_code, filename=target_rel)

        baseline_data = {
            "text": f"```python\n{base_code}\n```",
            "thinking": (
                "Generated from the full, unpruned repository context."
                if base_source == "model"
                else "Illustrative legacy pattern from this workspace's superseded decisions; not a model run."
            ),
            "code": base_code,
            "diff": base_diff,
            "latency_ms": base_latency,
            "unparseable": False,
            "source": base_source,
        }

        runs_cache[run_id] = {
            "owner": owner,
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

    return StreamingResponse(_released_after(event_stream(), owner), media_type="text/event-stream")



@app.post("/api/approve")
def approve_patch(req: ApproveRequest, request: Request) -> Dict[str, Any]:
    user = _current_user(request)
    workspace_root, graph, router, free_mode = _bind(request)
    if free_mode:
        raise HTTPException(status_code=409, detail="No workspace attached: nothing to commit.")
    if req.run_id not in runs_cache:
        raise HTTPException(status_code=409, detail="Run expired. Press Run again.")

    run = runs_cache[req.run_id]
    if run.get("owner") != user["id"]:
        raise HTTPException(status_code=403, detail="Only the person who started this run can approve it.")
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
        actor=user["email"],
    )
    _audit(request, "patch_refused" if result.get("refused") else "patch_applied",
           {"workspace": str(workspace_root), "run_id": req.run_id, "habit": result.get("habit_label")})

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
def get_memory(request: Request) -> Dict[str, Any]:
    workspace_root, graph, router, free_mode = _bind(request)
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
def get_memory_graph(request: Request) -> Dict[str, Any]:
    workspace_root, graph, router, free_mode = _bind(request)
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


# Live ingestion: ADRs or notes saved from any editor reload that workspace's
# memory within ~1s, for every workspace someone has open
adr_watcher = WorkspaceWatcher(
    get_root=lambda: memory.roots(),
    on_change=lambda changes: memory.reload(Path(changes["root"])),
)


@app.on_event("startup")
def _start_adr_watcher() -> None:
    # memory.get() ingested the default workspace at import, so ADRs edited
    # while the server was down are already current
    adr_watcher.start()


@app.on_event("shutdown")
def _stop_adr_watcher() -> None:
    adr_watcher.stop()


@app.get("/api/memory/changes")
def memory_changes(request: Request, since: int = 0) -> Dict[str, Any]:
    """Change events for the workspace this user has open (others' are not shown)."""
    workspace_root, graph, router, free_mode = _bind(request)
    mine = str(workspace_root)
    return {
        "seq": adr_watcher.last_seq,
        "events": [asdict(e) for e in adr_watcher.events_since(since) if not free_mode and e.root == mine],
    }


class SwitchWorkspaceRequest(BaseModel):
    path: str


@app.get("/api/workspace")
def get_workspace(request: Request) -> Dict[str, Any]:
    workspace_root, graph, router, free_mode = _bind(request)
    if free_mode:
        return {"workspace_root": None, "name": FREE_MODE_NAME, "exists": True, "adr_count": 0, "note_count": 0, "free": True}
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
def list_workspaces(request: Request) -> Dict[str, Any]:
    workspace_root, graph, router, free_mode = _bind(request)
    presets = [
        {
            "id": "__free__",
            "name": FREE_MODE_NAME,
            "path": "__free__",
            "repo_url": None,
            "title": "No workspace (unrestricted)",
            "domain": "General",
            "icon": "💬",
            "adrs": ["No ADRs", "No policy checks", "Nothing written to disk"],
            "desc": "Plain local assistant: requests go straight to the local model. Switch back to a workspace to re-enable ADR governance.",
        },
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
        "active": FREE_MODE_NAME if free_mode else workspace_root.name,
        "active_path": "(none)" if free_mode else str(workspace_root.resolve()),
        "free": free_mode,
        "presets": presets,
    }


@app.post("/api/workspace")
def switch_workspace(req: SwitchWorkspaceRequest, request: Request) -> Dict[str, Any]:
    """Switch this user's workspace (other users are unaffected)."""
    user = _current_user(request)
    state = _user_state(user)
    raw = req.path.strip()
    if raw.lower() in FREE_MODE_KEYS:
        state.free = True
        auth_store.set_last_workspace(user["id"], "__free__")
        return {
            "status": "switched",
            "workspace_root": "(none)",
            "name": FREE_MODE_NAME,
            "adr_count": 0,
            "note_count": 0,
            "free": True,
        }

    target_path = _resolve_workspace(raw)
    if not target_path.exists():
        raise HTTPException(status_code=400, detail=f"Directory '{target_path}' does not exist on disk.")
    if not target_path.is_dir():
        raise HTTPException(status_code=400, detail=f"Path '{target_path}' is not a directory.")

    memory.reload(target_path)
    state.root, state.free = target_path, False
    auth_store.set_last_workspace(user["id"], str(target_path))

    adr_count = len(list((target_path / "docs" / "adr").glob("*.md"))) if (target_path / "docs" / "adr").exists() else 0
    note_count = len(list((target_path / "notes").glob("*.md"))) if (target_path / "notes").exists() else 0

    return {
        "status": "switched",
        "workspace_root": str(target_path),
        "name": target_path.name,
        "adr_count": adr_count,
        "note_count": note_count,
    }


ADR_FILENAME = re.compile(r"^[A-Za-z0-9][\w.-]*\.md$")


def _adr_file(workspace_root: Path, adr_id: str, must_exist: bool = True) -> Path:
    """The ADR file for an id like 'adr:014-aegis-seal', confined to <workspace>/docs/adr."""
    stem = adr_id.removeprefix("adr:")
    filename = stem if stem.endswith(".md") else f"{stem}.md"
    adr_dir = (workspace_root / "docs" / "adr").resolve()
    if not ADR_FILENAME.match(filename) or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid ADR name.")
    filepath = (adr_dir / filename).resolve()
    if not filepath.is_relative_to(adr_dir):
        raise HTTPException(status_code=400, detail="Invalid ADR name.")
    if must_exist and not filepath.is_file():
        raise HTTPException(status_code=404, detail=f"ADR '{adr_id}' not found")
    return filepath


@app.get("/api/adrs")
def list_adrs(request: Request) -> Dict[str, Any]:
    workspace_root, graph, router, free_mode = _bind(request)
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
def get_adr(adr_id: str, request: Request) -> Dict[str, Any]:
    workspace_root, graph, router, free_mode = _bind(request)
    filepath = _adr_file(workspace_root, adr_id)

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
def create_adr(req: CreateAdrRequest, request: Request) -> Dict[str, Any]:
    workspace_root, graph, router, free_mode = _bind(request)
    fname = req.filename.strip() or f"adr-{uuid.uuid4().hex[:6]}.md"
    (workspace_root / "docs" / "adr").mkdir(parents=True, exist_ok=True)
    filepath = _adr_file(workspace_root, fname, must_exist=False)
    if filepath.exists():
        raise HTTPException(status_code=409, detail=f"ADR file '{filepath.name}' already exists")

    filepath.write_text(req.content.strip() + "\n", encoding="utf-8")
    memory.reload(workspace_root)
    _audit(request, "adr_created", {"workspace": str(workspace_root), "file": filepath.name})
    return {"status": "ok", "filename": filepath.name, "id": f"adr:{filepath.stem}"}


@app.put("/api/adr/{adr_id:path}")
def update_adr(adr_id: str, req: UpdateAdrRequest, request: Request) -> Dict[str, Any]:
    workspace_root, graph, router, free_mode = _bind(request)
    filepath = _adr_file(workspace_root, adr_id)

    filepath.write_text(req.content.strip() + "\n", encoding="utf-8")
    memory.reload(workspace_root)
    _audit(request, "adr_updated", {"workspace": str(workspace_root), "file": filepath.name})
    return {"status": "ok", "filename": filepath.name, "id": f"adr:{filepath.stem}"}


@app.delete("/api/adr/{adr_id:path}")
def delete_adr(adr_id: str, request: Request) -> Dict[str, Any]:
    workspace_root, graph, router, free_mode = _bind(request)
    filepath = _adr_file(workspace_root, adr_id)

    try:
        filepath.unlink()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete file: {e}")

    memory.reload(workspace_root)
    _audit(request, "adr_deleted", {"workspace": str(workspace_root), "file": filepath.name})
    return {"status": "ok", "filename": filepath.name, "id": f"adr:{filepath.stem}"}


class GenerateAdrRequest(BaseModel):
    prompt: str
    model_id: Optional[str] = None


@app.post("/api/adr/generate")
def generate_adr_stream(req: GenerateAdrRequest, request: Request):
    global generator
    workspace_root, graph, router, free_mode = _bind(request)
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("aegis.ui.server:app", host="127.0.0.1", port=8080, reload=False)

