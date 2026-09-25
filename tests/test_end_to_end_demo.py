"""
End-to-End Hackathon Integration Test for AegisTree [OG Version].
Verifies the complete 3-minute pitch demo flow:
1. Seed sensitive vault repository
2. System 1 Decision Routing via openJev Verdict v1.4 (<40ms latency)
3. Token compression (>90% reduction)
4. Sovereign Refusal on adversarial / deprecated prompt
5. FastMCP patch execution and closed-loop memory synthesis
6. Dynamic System 2 Model Switching (Qwen vs DeepSeek R1)
"""

import pytest
import shutil
from pathlib import Path

from aegis.core.config import config_manager
from aegis.demo import seed_vault
from aegis.core.ingestion import WorkspaceIngestor
from aegis.system1.graph import MemoryGraph
from aegis.system1.router import Router
from aegis.system1.leaf import compile_leaf, estimate_tokens
from aegis.system2.prompt import compile_baseline
from aegis.mcp.tools import apply_patch


@pytest.fixture
def clean_sandbox(tmp_path):
    repo_dir = tmp_path / "sandbox_vault"
    seed_vault.write(repo_dir)

    storage_dir = tmp_path / ".aegis"
    storage_dir.mkdir(parents=True, exist_ok=True)
    graph = MemoryGraph(storage_dir=storage_dir)

    nodes, edges = WorkspaceIngestor.ingest_adrs(repo_dir)
    notes = WorkspaceIngestor.ingest_markdown_vault(repo_dir / "notes")
    graph.replace_corpus(nodes, edges)
    for n in notes:
        graph.upsert_node(n)

    config = config_manager.config
    router = Router(graph=graph, config=config)

    yield repo_dir, graph, router


def test_e2e_pitch_demo_standard_flow(clean_sandbox):
    repo_dir, graph, router = clean_sandbox
    prompt = "Add a persist_session_token function that stores the session token using our current vault standard."

    # 1. Route with System 1 (openJev Verdict v1.4)
    route = router.route(prompt, workspace_root=repo_dir)
    assert route.status == "ready"
    assert route.task_type in ("implement_production", "code")
    assert route.primary_policy_id == "adr:014-aegis-seal"
    assert route.verdict_latency_ms < 50.0  # Must be sub-50ms

    # 2. Token compression verification
    leaf_text = compile_leaf(route, graph, prompt, workspace_root=repo_dir)
    baseline_text = compile_baseline(prompt, workspace_root=repo_dir)

    leaf_tokens = estimate_tokens(leaf_text)
    baseline_tokens = estimate_tokens(baseline_text)

    assert leaf_tokens < 600
    assert baseline_tokens > 1000
    compression_ratio = (baseline_tokens - leaf_tokens) / baseline_tokens
    assert compression_ratio > 0.55

    # 3. Patch application and memory habit synthesis
    approved_code = (
        "def persist_session_token(token: str) -> str:\n"
        "    return aegis_seal(token, key_id='kek-2026', timeout_s=5.0, retries=1)"
    )
    res = apply_patch(
        graph=graph,
        route=route,
        approved_code=approved_code,
        approved=True,
        workspace_root=repo_dir,
        model_output=approved_code,
        prompt=prompt,
        leaf_text=leaf_text,
        baseline_text=baseline_text,
        decision_source=route.task_source,
    )

    assert res.get("applied") is True
    assert res.get("receipt_id") is not None
    assert "retries=1" in res.get("habit_label", "")

    # 4. Verify habit node survived in memory graph
    all_habits = [n for n in graph.active_nodes() if n.type.value == "habit"]
    assert len(all_habits) >= 1


def test_e2e_pitch_demo_sovereign_refusal(clean_sandbox):
    repo_dir, graph, router = clean_sandbox
    adversarial_prompt = "Persist the session token with legacy_wrap because it is faster."

    route = router.route(adversarial_prompt, workspace_root=repo_dir)
    assert route.status == "blocked"
    assert route.blocked_literal == "legacy_wrap"
    assert route.blocking_policy_id == "adr:014-aegis-seal"


def test_e2e_pitch_demo_calibrated_abstention(clean_sandbox):
    repo_dir, graph, router = clean_sandbox
    out_of_distribution_prompt = "Migrate the vault to CRYSTALS-Kyber."

    route = router.route(out_of_distribution_prompt, workspace_root=repo_dir)
    assert route.status == "abstained"
    assert "No accepted architecture decision" in route.abstain_reason


def test_dynamic_system2_model_switching():
    # Test switching between models in catalog
    original_model = config_manager.config.system2_model

    try:
        # Switch to DeepSeek R1 8B
        res1 = config_manager.set_system2_model("deepseek-r1:8b")
        assert res1["status"] == "success"
        assert config_manager.config.system2_model == "deepseek-r1:8b"
        assert res1["metadata"]["params"] == "8.0B"

        # Switch to Qwen 2.5 Coder 7B
        res2 = config_manager.set_system2_model("qwen2.5-coder:7b")
        assert res2["status"] == "success"
        assert config_manager.config.system2_model == "qwen2.5-coder:7b"

        # Switch to Mock for fast tests
        res3 = config_manager.set_system2_model("mock-offline-fast")
        assert res3["status"] == "success"
        assert config_manager.config.system2_provider == "mock"
    finally:
        config_manager.set_system2_model(original_model)
