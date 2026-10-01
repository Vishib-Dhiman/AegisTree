from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import aegis.ui.server as srv
from aegis.system2.prompt import compile_baseline


class FakeModel:
    def __init__(self):
        self.prompts = []

    def complete(self, prompt, images=None):
        self.prompts.append(prompt)
        return SimpleNamespace(
            text="```python\ndef persist_token_v2(token: str) -> str:\n    return legacy_wrap(token, 'kek-2024', 30)\n```",
            latency_ms=12.0,
        )


def _request(user_id):
    return SimpleNamespace(state=SimpleNamespace(user={"id": user_id, "email": f"u{user_id}@example.com"}))


@pytest.fixture
def cached_run(monkeypatch):
    model = FakeModel()
    monkeypatch.setattr(srv, "_generator_for", lambda images: (model, "fake-coder", False))
    srv.runs_cache["r-base"] = {
        "owner": 1,
        "baseline": srv._baseline_not_run(),
        "baseline_run_text": "REPOSITORY FILES:\n...\nUSER REQUEST:\nPersist the token",
        "target_function": "persist_token_v2",
        "old_fn_source": "def persist_token_v2(token: str) -> str:\n    raise NotImplementedError\n",
        "target_file": "vault/store.py",
    }
    yield model
    srv.runs_cache.pop("r-base", None)


def test_baseline_is_a_real_model_run_on_request(cached_run):
    result = srv.run_baseline("r-base", _request(1))
    assert result["source"] == "model" and result["model"] == "fake-coder"
    assert "legacy_wrap" in result["diff"] and result["diff"].startswith("--- a/vault/store.py")
    assert cached_run.prompts == ["REPOSITORY FILES:\n...\nUSER REQUEST:\nPersist the token"]
    # A second press reuses the answer instead of running the model again
    assert srv.run_baseline("r-base", _request(1)) == result and len(cached_run.prompts) == 1


def test_only_the_owner_can_run_the_baseline(cached_run):
    with pytest.raises(HTTPException) as ex:
        srv.run_baseline("r-base", _request(2))
    assert ex.value.status_code == 403 and not cached_run.prompts
    with pytest.raises(HTTPException) as ex:
        srv.run_baseline("missing", _request(1))
    assert ex.value.status_code == 404


def test_capped_baseline_keeps_the_target_file_first(test_vault):
    full = compile_baseline("persist", test_vault, "persist_session_token", "vault/store.py")
    capped = compile_baseline("persist", test_vault, "persist_session_token", "vault/store.py", max_chars=1500)
    assert len(capped) < len(full)
    assert capped.index("----- vault/store.py -----") < capped.index("did not fit")
    assert "complete function named persist_session_token in vault/store.py" in capped


class StreamingFake(FakeModel):
    def complete_stream(self, prompt, images=None):
        yield {"response": "```python\ndef persist_session_token(token: str) -> str:\n"
                           "    return aegis_seal(token, key_id='kek-2026', timeout_s=5.0, retries=1)\n```"}


def test_streamed_run_defers_the_comparison_then_runs_it(monkeypatch, test_vault, tmp_path):
    import asyncio
    import json
    from starlette.requests import Request as StarletteRequest
    from aegis.core.ingestion import WorkspaceIngestor
    from aegis.system1.graph import MemoryGraph
    from aegis.system1.router import Router

    graph = MemoryGraph(storage_dir=tmp_path / ".aegis")
    graph.replace_corpus(*WorkspaceIngestor.ingest_adrs(test_vault))
    router = Router(graph=graph, config=srv.config, engine=srv.memory.engine)
    model = StreamingFake()
    monkeypatch.setattr(srv, "_bind", lambda request: (test_vault, graph, router, False))
    monkeypatch.setattr(srv, "_generator_for", lambda images: (model, "fake-coder", False))
    request = StarletteRequest({"type": "http", "client": ("127.0.0.1", 1), "headers": []})
    request.state.user = {"id": 1, "email": "tester@example.com"}
    req = srv.RunRequest(prompt="Add a persist_session_token function that stores the session token using our current vault standard.")
    resp = srv.run_prompt_stream(req, request)

    async def collect():
        return [chunk async for chunk in resp.body_iterator]

    events = [json.loads(c[len("data: "):]) for c in asyncio.run(collect()) if c.startswith("data: ")]
    done = events[-1]
    assert done["type"] == "finished" and done["target_file"] == "vault/store.py"
    assert done["baseline"]["source"] == "not_run" and not model.prompts  # nothing ran yet
    assert "aegis_seal" in done["aegis"]["diff"]

    # Demo functions get the labelled scripted example, without a model call
    result = srv.run_baseline(done["run_id"], request)
    assert result["source"] == "illustrative" and not model.prompts
    assert "legacy_wrap" in result["diff"] and result["model"] is None
    srv.runs_cache.pop(done["run_id"], None)
