from datetime import datetime, timezone
from pathlib import Path
import pytest

from aegis.core.ingestion import WorkspaceIngestor
from aegis.core.models import NodeType
from aegis.mcp.tools import apply_patch
from aegis.system1.graph import MemoryGraph
from aegis.system1.leaf import compile_leaf
from aegis.system1.router import Router
from aegis.system2.client import MockGenerator


def test_feedback_loop_and_retries_memory(tmp_path: Path, test_vault: Path):
    storage = tmp_path / ".aegis"
    graph = MemoryGraph(storage_dir=storage)
    nodes, edges = WorkspaceIngestor.ingest_adrs(test_vault)
    graph.replace_corpus(nodes, edges)

    router = Router(graph=graph)
    generator = MockGenerator()
    now = datetime(2026, 9, 24, tzinfo=timezone.utc)

    # 1. Persist prompt
    persist_prompt = "Add a persist_session_token function that stores the session token using our current vault standard."
    route1 = router.route(prompt=persist_prompt, workspace_root=test_vault, now=now)
    leaf1 = compile_leaf(route=route1, graph=graph, prompt=persist_prompt, workspace_root=test_vault)

    # Mock generator returns default retries=3
    gen1 = generator.complete(leaf1)
    assert "retries=3" in gen1.text

    # Check: apply with approved=False does not change store.py
    store_file = test_vault / "vault" / "store.py"
    initial_store_content = store_file.read_text(encoding="utf-8")

    res_unapproved = apply_patch(
        graph=graph,
        route=route1,
        approved_code=gen1.text,
        approved=False,
        workspace_root=test_vault,
        model_output=gen1.text,
        prompt=persist_prompt,
        leaf_text=leaf1,
    )
    assert res_unapproved["applied"] is False
    assert res_unapproved["reason"] == "human approval required"
    assert store_file.read_text(encoding="utf-8") == initial_store_content

    # 2. Check: approving a body that contains legacy_wrap returns refusal and does not create a habit
    banned_code = (
        'def persist_session_token(token: str) -> str:\n'
        '    return legacy_wrap(token, key_id="kek-2024", timeout_s=30)\n'
    )
    res_banned = apply_patch(
        graph=graph,
        route=route1,
        approved_code=banned_code,
        approved=True,
        workspace_root=test_vault,
        model_output=gen1.text,
        prompt=persist_prompt,
        leaf_text=leaf1,
    )
    assert res_banned["applied"] is False
    assert res_banned["refused"] is True
    assert "legacy_wrap" in res_banned["banned_literal"]
    assert len([n for n in graph.all_nodes() if n.type == NodeType.HABIT]) == 0
    assert store_file.read_text(encoding="utf-8") == initial_store_content

    # 3. Approve a body with retries=1
    edited_code = (
        'def persist_session_token(token: str) -> str:\n'
        '    return aegis_seal(token, key_id="kek-2026", timeout_s=5.0, retries=1)\n'
    )
    res_approved = apply_patch(
        graph=graph,
        route=route1,
        approved_code=edited_code,
        approved=True,
        workspace_root=test_vault,
        model_output=gen1.text,
        prompt=persist_prompt,
        leaf_text=leaf1,
    )
    assert res_approved["applied"] is True
    assert res_approved["refused"] is False
    assert "store.py" in str(store_file)
    assert "retries=1" in store_file.read_text(encoding="utf-8")

    # A habit exists
    habits = [n for n in graph.active_nodes() if n.type == NodeType.HABIT]
    assert len(habits) == 1
    assert "retries=1" in habits[0].label

    # 4. A second rotate route's leaf contains retries=1
    rotate_prompt = "Add a rotate_session_token function using our current vault standard."
    route2 = router.route(prompt=rotate_prompt, workspace_root=test_vault)
    leaf2 = compile_leaf(route=route2, graph=graph, prompt=rotate_prompt, workspace_root=test_vault)

    assert "retries=1" in leaf2
    # Verify mock generator also emits retries=1 when prompt contains retries=1
    gen2 = generator.complete(leaf2)
    assert "retries=1" in gen2.text
    assert "rotate_session_token" in gen2.text
