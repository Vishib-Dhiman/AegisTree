from pathlib import Path

from aegis.core.ingestion import WorkspaceIngestor
from aegis.core.models import NodeType
from aegis.demo import seed_vault
from aegis.mcp.tools import apply_patch
from aegis.system1.graph import MemoryGraph
from aegis.system1.router import Router
from tests.test_policy_guard import ScriptedEngine

PROMPT = "Add a persist_session_token function that stores the session token using our current vault standard."
MODEL = (
    "def persist_session_token(token: str) -> str:\n"
    '    return aegis_seal(token, key_id="kek-2026", timeout_s=5.0, retries=3)\n'
)


def approve_with_retries(graph, router, root: Path, retries: int):
    route = router.route(PROMPT, workspace_root=root)
    approved = MODEL.replace("retries=3", f"retries={retries}")
    res = apply_patch(graph, route, approved, True, workspace_root=root, model_output=MODEL, prompt=PROMPT)
    assert res["applied"] is True


def habit_labels(route):
    return sorted(h.label for h in route.habits)


def test_habits_stay_in_the_workspace_that_learned_them(tmp_path: Path):
    a, b = tmp_path / "a" / "demo_vault", tmp_path / "b" / "demo_vault"
    seed_vault.write(a)
    seed_vault.write(b)
    graph = MemoryGraph(storage_dir=tmp_path / ".aegis")
    graph.replace_corpus(*WorkspaceIngestor.ingest_adrs(a))
    router = Router(graph=graph, engine=ScriptedEngine())

    approve_with_retries(graph, router, a, 1)
    approve_with_retries(graph, router, b, 5)

    assert habit_labels(router.route(PROMPT, workspace_root=a)) == ["Calls to aegis_seal must set retries=1."]
    assert habit_labels(router.route(PROMPT, workspace_root=b)) == ["Calls to aegis_seal must set retries=5."]
    # Learning retries=5 in b did not supersede retries=1 in a
    active = [n for n in graph.active_nodes() if n.type == NodeType.HABIT]
    assert len(active) == 2


def test_new_habit_supersedes_old_one_in_same_workspace(tmp_path: Path, test_vault: Path):
    graph = MemoryGraph(storage_dir=tmp_path / ".aegis")
    graph.replace_corpus(*WorkspaceIngestor.ingest_adrs(test_vault))
    router = Router(graph=graph, engine=ScriptedEngine())

    approve_with_retries(graph, router, test_vault, 1)
    approve_with_retries(graph, router, test_vault, 2)
    assert habit_labels(router.route(PROMPT, workspace_root=test_vault)) == ["Calls to aegis_seal must set retries=2."]


def test_untagged_legacy_habits_still_apply_everywhere(tmp_path: Path, test_vault: Path):
    graph = MemoryGraph(storage_dir=tmp_path / ".aegis")
    graph.replace_corpus(*WorkspaceIngestor.ingest_adrs(test_vault))
    graph.add_habit("Production vault calls must set retries=1.")
    route = Router(graph=graph, engine=ScriptedEngine()).route(PROMPT, workspace_root=test_vault)
    assert habit_labels(route) == ["Production vault calls must set retries=1."]
