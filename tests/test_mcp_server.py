import asyncio
from pathlib import Path

import pytest

fastmcp = pytest.importorskip("fastmcp")

from aegis.core.ingestion import WorkspaceIngestor
from aegis.mcp.server import build_server
from aegis.system1.graph import MemoryGraph
from aegis.system1.router import Router
from tests.test_retrieval import RetrievalEngine


def call(server, name, args):
    async def go():
        async with fastmcp.Client(server) as client:
            return await client.call_tool(name, args)
    return asyncio.run(go())


@pytest.fixture
def server(tmp_path: Path, test_vault: Path):
    graph = MemoryGraph(storage_dir=tmp_path / ".aegis")
    graph.replace_corpus(*WorkspaceIngestor.ingest_adrs(test_vault))
    router = Router(graph=graph, engine=RetrievalEngine("adr:025-ephemeral-session-ttl"))
    return build_server(graph=graph, router=router, workspace_root=test_vault)


def test_lists_the_three_tools(server):
    async def go():
        async with fastmcp.Client(server) as client:
            return sorted(t.name for t in await client.list_tools())
    assert asyncio.run(go()) == ["apply_patch", "propose_patch", "search_decisions"]


def test_search_decisions_uses_verdict_retrieval(server):
    res = call(server, "search_decisions", {"query": "Make sessions last forever."})
    data = res.data if hasattr(res, "data") and res.data is not None else res.structured_content
    assert data["overlapping_ids"][0] == "adr:025-ephemeral-session-ttl"
    assert data["retrieval_source"] == "verdict"


def test_apply_patch_refuses_banned_literal(server, test_vault: Path):
    code = 'def persist_session_token(token: str) -> str:\n    return legacy_wrap(token, key_id="kek-2024")\n'
    res = call(server, "apply_patch", {
        "prompt": "Add a persist_session_token function that stores the session token using our current vault standard.",
        "approved_code": code,
        "approved": True,
    })
    data = res.data if hasattr(res, "data") and res.data is not None else res.structured_content
    assert data["applied"] is False and data["refused"] is True
    assert "legacy_wrap" not in (test_vault / "vault" / "store.py").read_text()
