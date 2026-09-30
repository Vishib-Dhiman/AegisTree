from datetime import datetime, timezone
from pathlib import Path

import pytest

from aegis.core.ingestion import WorkspaceIngestor
from aegis.core.models import (
    ChoiceQuery,
    ChoiceResult,
    NodeType,
    NoulQuery,
    NoulResult,
    ScoreQuery,
    ScoreResult,
)
from aegis.mcp.feedback import extract_habits
from aegis.mcp.tools import apply_patch
from aegis.system1.engine import DecisionEngine, EngineUnavailable
from aegis.system1.graph import MemoryGraph
from aegis.system1.policy_guard import contains_literal, find_forbidden
from aegis.system1.router import Router, build_context, relative_confidence

NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


class ScriptedEngine(DecisionEngine):
    """Implement task at low confidence; revival check answers with `revival_prob`."""

    def __init__(self, revival_prob: float = 0.0):
        self.revival_prob = revival_prob
        self.contexts = []

    @property
    def engine_name(self) -> str:
        return "scripted"

    @property
    def is_airgapped(self) -> bool:
        return True

    def evaluate_choice(self, context: str, query: ChoiceQuery) -> ChoiceResult:
        self.contexts.append(context)
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


@pytest.mark.parametrize("text", [
    "use legacy_wrap", "use LegacyWrap", "use legacy-wrap", "use legacy wrap", "use legacywrap", "LEGACY_WRAP()",
])
def test_literal_variants_match(text):
    assert contains_literal(text, "legacy_wrap")


@pytest.mark.parametrize("text", [
    "wrap the call in try/except", "legacy code should wrap errors", "timeout_s=300",
])
def test_literal_non_matches(text):
    assert not find_forbidden(text, ["legacy_wrap", "timeout_s=30"])


def test_relative_confidence_ignores_abstention_mass():
    probs = {"a": 0.6, "b": 0.1, "__insufficient_evidence__": 0.3}
    assert relative_confidence(probs, "a", {"a", "b"}) == pytest.approx(0.6 / 0.7)


def test_context_names_active_workspace():
    assert build_context("hi", "repos/sqlalchemy").startswith("Repository: sqlalchemy.")
    assert build_context("hi", "demo_vault").startswith("Repository: demo vault.")


def test_camelcase_literal_request_is_blocked(graph, test_vault):
    route = Router(graph=graph, engine=ScriptedEngine()).route(
        "Persist the session token with LegacyWrap.", workspace_root=test_vault, now=NOW)
    assert route.status == "blocked"
    assert route.block_method == "literal"
    assert route.blocked_literal == "legacy_wrap"


def test_paraphrased_revival_is_blocked(graph, test_vault):
    route = Router(graph=graph, engine=ScriptedEngine(revival_prob=0.85)).route(
        "Store session tokens with the old wrap cipher, it's quicker.", workspace_root=test_vault, now=NOW)
    assert route.status == "blocked"
    assert route.block_method == "semantic"
    assert route.revived_policy_id == "adr:003-legacy-wrap"
    assert route.blocking_policy_id == "adr:014-aegis-seal"


def test_low_revival_probability_is_not_blocked(graph, test_vault):
    route = Router(graph=graph, engine=ScriptedEngine(revival_prob=0.4)).route(
        "Store session tokens with the old wrap cipher, it's quicker.", workspace_root=test_vault, now=NOW)
    assert route.status == "ready"


def test_habits_learned_for_any_call_and_argument():
    habits = extract_habits(
        "engine = create_engine(url, pool_size=5)",
        "engine = create_engine(url, pool_size=20, echo=False)",
    )
    assert [h["label"] for h in habits] == [
        "Calls to create_engine must set pool_size=20.",
        "Calls to create_engine must set echo=False.",
    ]
    assert habits[0]["previous_value"] == "5"


def test_unedited_approval_learns_nothing():
    code = 'aegis_seal(token, key_id="kek-2026", timeout_s=5.0, retries=3)'
    assert extract_habits(code, code) == []


def test_apply_patch_records_every_changed_argument(graph, test_vault):
    prompt = "Add a persist_session_token function that stores the session token using our current vault standard."
    route = Router(graph=graph, engine=ScriptedEngine()).route(prompt, workspace_root=test_vault, now=NOW)
    model = (
        "```python\ndef persist_session_token(token: str) -> str:\n"
        '    return aegis_seal(token, key_id="kek-2026", timeout_s=5.0, retries=3)\n```'
    )
    approved = (
        "def persist_session_token(token: str) -> str:\n"
        '    return aegis_seal(token, key_id="kek-2026", timeout_s=2.5, retries=1)\n'
    )
    res = apply_patch(graph, route, approved, True, workspace_root=test_vault, model_output=model, prompt=prompt)
    assert res["applied"] is True
    labels = sorted(n.label for n in graph.active_nodes() if n.type == NodeType.HABIT)
    assert labels == [
        "Calls to aegis_seal must set retries=1.",
        "Calls to aegis_seal must set timeout_s=2.5.",
    ]
