from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
import pytest

from aegis.core.config import SystemConfig
from aegis.core.ingestion import WorkspaceIngestor
from aegis.core.models import (
    ChoiceQuery,
    ChoiceResult,
    NoulQuery,
    NoulResult,
    ScoreQuery,
    ScoreResult,
)
from aegis.system1.engine import DecisionEngine, EngineUnavailable
from aegis.system1.graph import MemoryGraph
from aegis.system1.router import Router


class BrokenEngine(DecisionEngine):
    """Engine that always raises EngineUnavailable."""

    @property
    def engine_name(self) -> str:
        return "broken"

    @property
    def is_airgapped(self) -> bool:
        return True

    def evaluate_choice(self, context: str, query: ChoiceQuery) -> ChoiceResult:
        raise EngineUnavailable("Verdict engine unavailable in test")

    def evaluate_score(self, context: str, query: ScoreQuery) -> ScoreResult:
        raise EngineUnavailable("Verdict engine unavailable in test")

    def evaluate_noul(self, context: str, query: NoulQuery) -> NoulResult:
        raise EngineUnavailable("Verdict engine unavailable in test")


class MockVerdictEngine(DecisionEngine):
    """Engine that returns configured choice response."""

    def __init__(self, selected_id: str, confidence: float):
        self.selected_id = selected_id
        self.confidence = confidence

    @property
    def engine_name(self) -> str:
        return "mock_verdict"

    @property
    def is_airgapped(self) -> bool:
        return True

    def evaluate_choice(self, context: str, query: ChoiceQuery) -> ChoiceResult:
        return ChoiceResult(
            query_id=query.id,
            selected_id=self.selected_id,
            confidence=self.confidence,
            probabilities={self.selected_id: self.confidence},
            is_abstention=False,
            latency_ms=1.5,
        )

    def evaluate_score(self, context: str, query: ScoreQuery) -> ScoreResult:
        raise NotImplementedError()

    def evaluate_noul(self, context: str, query: NoulQuery) -> NoulResult:
        raise NotImplementedError()


@pytest.fixture
def populated_graph(tmp_path: Path, test_vault: Path) -> tuple[MemoryGraph, Path]:
    storage = tmp_path / ".aegis"
    graph = MemoryGraph(storage_dir=storage)
    nodes, edges = WorkspaceIngestor.ingest_adrs(test_vault)
    graph.replace_corpus(nodes, edges)
    return graph, test_vault


def test_persist_prompt_with_engine_unavailable(populated_graph):
    graph, vault_dir = populated_graph
    broken_engine = BrokenEngine()
    router = Router(graph=graph, engine=broken_engine)

    prompt = "Add a persist_session_token function that stores the session token using our current vault standard."
    res = router.route(
        prompt=prompt,
        workspace_root=vault_dir,
        now=datetime(2026, 9, 24, tzinfo=timezone.utc),
    )

    assert res.status == "ready"
    assert res.task_type == "implement_production"
    assert res.task_source == "keyword"
    assert res.primary_policy_id == "adr:014-aegis-seal"
    assert "adr:014-aegis-seal" in res.active_policy_ids
    assert any(neg.id == "adr:003-legacy-wrap" for neg in res.negative_nodes)
    assert any("test_legacy_wrap.py" in ef["path"] for ef in res.excluded_files)


def test_kyber_prompt_abstains_no_generator_call(populated_graph):
    graph, vault_dir = populated_graph
    router = Router(graph=graph, engine=BrokenEngine())

    prompt = "Migrate the vault to CRYSTALS-Kyber."
    generator_call_count = 0

    res = router.route(
        prompt=prompt,
        workspace_root=vault_dir,
        now=datetime(2026, 9, 24, tzinfo=timezone.utc),
    )

    # Status must be abstained
    assert res.status == "abstained"
    assert res.primary_policy_id is None
    assert res.active_policy_ids == []
    assert res.abstain_reason is not None
    assert "CRYSTALS-Kyber" in res.abstain_reason

    # On abstain, caller must not invoke generator
    if res.status == "ready":
        generator_call_count += 1
    assert generator_call_count == 0


def test_explain_prompt_keyword_fallback(populated_graph):
    graph, vault_dir = populated_graph
    router = Router(graph=graph, engine=BrokenEngine())

    prompt = "Explain how session tokens are stored."
    res = router.route(
        prompt=prompt,
        workspace_root=vault_dir,
        now=datetime(2026, 9, 24, tzinfo=timezone.utc),
    )

    assert res.status == "ready"
    assert res.task_type == "explain_only"
    assert res.task_source == "keyword"
    assert res.primary_policy_id == "adr:014-aegis-seal"


def test_edit_tests_keyword_rule(populated_graph):
    graph, vault_dir = populated_graph
    router = Router(graph=graph, engine=BrokenEngine())

    prompt = "Please update the tests for legacy wrap"
    res = router.route(
        prompt=prompt,
        workspace_root=vault_dir,
        now=datetime(2026, 9, 24, tzinfo=timezone.utc),
    )

    assert res.status == "ready"
    assert res.task_type == "edit_tests"
    assert res.task_source == "keyword"


def test_verdict_high_confidence_locks_threshold(populated_graph):
    graph, vault_dir = populated_graph
    # Engine returns edit_tests at 0.99 confidence for persist prompt
    mock_engine = MockVerdictEngine(selected_id="edit_tests", confidence=0.99)
    config = SystemConfig(system1_confidence_threshold=0.55)
    router = Router(graph=graph, config=config, engine=mock_engine)

    prompt = "Add a persist_session_token function that stores the session token using our current vault standard."
    res = router.route(
        prompt=prompt,
        workspace_root=vault_dir,
        now=datetime(2026, 9, 24, tzinfo=timezone.utc),
    )

    assert res.task_type == "edit_tests"
    assert res.task_source == "verdict"
    assert res.verdict_confidence == 0.99


def test_verdict_low_confidence_falls_back_to_keyword(populated_graph):
    graph, vault_dir = populated_graph
    # Engine returns explain_only at 0.40 confidence (below threshold 0.55)
    mock_engine = MockVerdictEngine(selected_id="explain_only", confidence=0.40)
    config = SystemConfig(system1_confidence_threshold=0.55)
    router = Router(graph=graph, config=config, engine=mock_engine)

    prompt = "Add a persist_session_token function that stores the session token using our current vault standard."
    res = router.route(
        prompt=prompt,
        workspace_root=vault_dir,
        now=datetime(2026, 9, 24, tzinfo=timezone.utc),
    )

    assert res.task_type == "implement_production"
    assert res.task_source == "keyword"
    assert res.verdict_task_id == "explain_only"
    assert res.verdict_confidence == 0.40


def test_force_legacy_wrap_is_blocked(populated_graph):
    graph, vault_dir = populated_graph
    router = Router(graph=graph, engine=BrokenEngine())
    prompt = "Persist the session token with legacy_wrap because it is faster."
    result = router.route(
        prompt=prompt,
        workspace_root=vault_dir,
        now=datetime(2026, 9, 24, tzinfo=timezone.utc),
    )

    assert result.status == "blocked"
    assert result.blocked_literal == "legacy_wrap"
    assert result.blocking_policy_id == "adr:014-aegis-seal"
    assert result.task_type == "implement_production"


def test_force_legacy_wrap_does_not_call_generator(populated_graph):
    graph, vault_dir = populated_graph
    router = Router(graph=graph, engine=BrokenEngine())
    prompt = "Persist the session token with legacy_wrap because it is faster."
    route = router.route(
        prompt=prompt,
        workspace_root=vault_dir,
        now=datetime(2026, 9, 24, tzinfo=timezone.utc),
    )

    calls = 0
    if route.status == "ready":
        calls += 1

    assert route.status == "blocked"
    assert calls == 0


def test_explain_legacy_wrap_not_blocked(populated_graph):
    graph, vault_dir = populated_graph
    router = Router(graph=graph, engine=BrokenEngine())
    prompt = "Explain why legacy_wrap was deprecated."
    result = router.route(
        prompt=prompt,
        workspace_root=vault_dir,
        now=datetime(2026, 9, 24, tzinfo=timezone.utc),
    )

    assert result.status == "ready"
    assert result.task_type == "explain_only"


def test_edit_tests_with_legacy_wrap_not_blocked(populated_graph):
    graph, vault_dir = populated_graph
    router = Router(graph=graph, engine=BrokenEngine())
    prompt = "Update the tests for legacy_wrap."
    result = router.route(
        prompt=prompt,
        workspace_root=vault_dir,
        now=datetime(2026, 9, 24, tzinfo=timezone.utc),
    )

    assert result.status == "ready"
    assert result.task_type == "edit_tests"


def test_kyber_abstains_not_blocks(populated_graph):
    graph, vault_dir = populated_graph
    router = Router(graph=graph, engine=BrokenEngine())
    prompt = "Migrate the vault to CRYSTALS-Kyber."
    result = router.route(
        prompt=prompt,
        workspace_root=vault_dir,
        now=datetime(2026, 9, 24, tzinfo=timezone.utc),
    )

    assert result.status == "abstained"
    assert "blocked" not in (result.abstain_reason or "").lower()
