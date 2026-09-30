from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pytest

from aegis.core.ingestion import WorkspaceIngestor
from aegis.core.models import (
    ChoiceQuery,
    ChoiceResult,
    NoulQuery,
    NoulResult,
    ScoreQuery,
    ScoreResult,
)
from aegis.mcp.tools import search_decisions
from aegis.system1.engine import DecisionEngine, EngineUnavailable
from aegis.system1.graph import MemoryGraph
from aegis.system1.policy_guard import contains_literal
from aegis.system1.retrieval import NONE_ID
from aegis.system1.router import Router

NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


class RetrievalEngine(DecisionEngine):
    """Answers the policy_retrieval query with `pick` at `confidence`; revival checks
    with `revival_prob`; task classification is unavailable (keyword rule)."""

    def __init__(self, pick: str, confidence: float = 0.9, revival_prob: float = 0.0):
        self.pick = pick
        self.confidence = confidence
        self.revival_prob = revival_prob

    @property
    def engine_name(self) -> str:
        return "retrieval-scripted"

    @property
    def is_airgapped(self) -> bool:
        return True

    def evaluate_choice(self, context: str, query: ChoiceQuery) -> ChoiceResult:
        if query.id == "policy_retrieval":
            others = [o.id for o in query.options if o.id != self.pick]
            probs = {oid: (1.0 - self.confidence) / len(others) for oid in others}
            probs[self.pick] = self.confidence
            return ChoiceResult(query_id=query.id, selected_id=self.pick, confidence=self.confidence, probabilities=probs)
        if query.id == "revival_check":
            probs = {"revives": self.revival_prob, "compliant": 1.0 - self.revival_prob}
            return ChoiceResult(query_id=query.id, selected_id="revives", confidence=self.revival_prob, probabilities=probs)
        raise EngineUnavailable("task classification not scripted")

    def evaluate_score(self, context: str, query: ScoreQuery) -> ScoreResult:
        raise NotImplementedError()

    def evaluate_noul(self, context: str, query: NoulQuery) -> NoulResult:
        raise NotImplementedError()


@pytest.fixture
def graph(tmp_path: Path, test_vault: Path) -> MemoryGraph:
    g = MemoryGraph(storage_dir=tmp_path / ".aegis")
    g.replace_corpus(*WorkspaceIngestor.ingest_adrs(test_vault))
    return g


def route(graph, vault, prompt, engine: Optional[DecisionEngine]):
    return Router(graph=graph, engine=engine).route(prompt, workspace_root=vault, now=NOW)


def test_semantic_pick_without_overlap_routes_to_decision(graph, test_vault):
    prompt = "Make sessions last forever so users never log out."
    res = route(graph, test_vault, prompt, RetrievalEngine("adr:025-ephemeral-session-ttl"))
    assert res.status == "ready"
    assert res.primary_policy_id == "adr:025-ephemeral-session-ttl"
    assert res.policy_source == "verdict"
    assert res.retrieval_source == "verdict"


def test_low_confidence_pick_falls_back_to_overlap(graph, test_vault):
    prompt = "Add a persist_session_token function that stores the session token using our current vault standard."
    res = route(graph, test_vault, prompt, RetrievalEngine("adr:025-ephemeral-session-ttl", confidence=0.3))
    assert res.primary_policy_id == "adr:014-aegis-seal"
    assert res.retrieval_source == "overlap"


def test_none_pick_without_overlap_abstains(graph, test_vault):
    res = route(graph, test_vault, "Add a dark mode toggle to the admin page.", RetrievalEngine(NONE_ID))
    assert res.status == "abstained"
    assert "none of these" in res.abstain_reason


def test_superseded_pick_routes_to_successor_and_assist_blocks(graph, test_vault):
    prompt = "Go back to how we sealed tokens in 2024."
    res = route(graph, test_vault, prompt, RetrievalEngine("adr:003-legacy-wrap", revival_prob=0.55))
    assert res.status == "blocked"
    assert res.block_method == "semantic"
    assert res.revived_policy_id == "adr:003-legacy-wrap"
    assert res.blocking_policy_id == "adr:014-aegis-seal"


def test_superseded_pick_below_assist_threshold_is_not_blocked(graph, test_vault):
    prompt = "Go back to how we sealed tokens in 2024."
    res = route(graph, test_vault, prompt, RetrievalEngine("adr:003-legacy-wrap", revival_prob=0.3))
    assert res.status == "ready"
    assert res.primary_policy_id == "adr:014-aegis-seal"


def test_two_hop_superseded_pick_resolves_to_active_successor(graph, test_vault):
    # ADR-001 -> superseded by ADR-003 -> superseded by ADR-014
    assert graph.active_successor("adr:001-in-memory-token-cache", NOW).id == "adr:014-aegis-seal"


def test_search_decisions_matches_router(graph, test_vault):
    engine = RetrievalEngine("adr:025-ephemeral-session-ttl")
    found = search_decisions(graph, "Make sessions last forever.", now=NOW, engine=engine, workspace_root=test_vault)
    assert found["overlapping_ids"][0] == "adr:025-ephemeral-session-ttl"
    assert found["retrieval_source"] == "verdict"


def test_code_shaped_literals_do_not_match_plain_words():
    assert not contains_literal("Serialize the model to a plain dict.", ".dict()")
    assert contains_literal("return model.dict()", ".dict()")
    assert contains_literal("use LegacyWrap", "legacy_wrap")
