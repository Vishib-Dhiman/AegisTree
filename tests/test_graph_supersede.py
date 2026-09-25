from datetime import datetime, timezone
from pathlib import Path
from aegis.core.ingestion import WorkspaceIngestor, get_superseded_closure
from aegis.core.models import EpistemicStatus


def test_graph_supersede(test_vault: Path):
    nodes, edges = WorkspaceIngestor.ingest_adrs(test_vault)

    nodes_by_id = {n.id: n for n in nodes}
    assert "adr:014-aegis-seal" in nodes_by_id
    assert "adr:003-legacy-wrap" in nodes_by_id

    adr_014 = nodes_by_id["adr:014-aegis-seal"]
    adr_003 = nodes_by_id["adr:003-legacy-wrap"]

    query_time = datetime(2026, 9, 24, 0, 0, 0, tzinfo=timezone.utc)

    # At 2026-09-24, ADR-014 is active, ADR-003 is not
    assert adr_014.is_active(query_time) is True
    assert adr_003.is_active(query_time) is False
    assert adr_003.epistemic_status == EpistemicStatus.SUPERSEDED

    # Find the supersedes edge
    supersedes_edges = [
        e for e in edges
        if e.source == "adr:014-aegis-seal" and e.relation == "supersedes"
    ]
    assert len(supersedes_edges) == 1
    edge = supersedes_edges[0]
    assert edge.target == "adr:003-legacy-wrap"
    assert edge.deprecated_at is None
    assert edge.is_active(query_time) is True

    # ADR-003 forbidden_literals contain legacy_wrap, kek-2024, timeout_s=30
    for lit in ["legacy_wrap", "kek-2024", "timeout_s=30"]:
        assert lit in adr_003.forbidden_literals

    # Closure from ADR-014 yields ADR-003
    closure = get_superseded_closure(["adr:014-aegis-seal"], nodes, edges)
    closure_ids = [n.id for n in closure]
    assert "adr:003-legacy-wrap" in closure_ids


def test_habit_survives_new_memory_graph_instance(tmp_path: Path):
    from aegis.system1.graph import MemoryGraph
    from aegis.core.models import NodeType, EpistemicStatus

    storage = tmp_path / ".aegis"
    mg1 = MemoryGraph(storage_dir=storage)
    habit_text = "Production vault calls must set retries=1."
    habit_node = mg1.add_habit(habit_text, source_receipt_id=1)

    assert habit_node.id.startswith("habit:")
    assert habit_node.label == habit_text
    assert habit_node.type == NodeType.HABIT
    assert habit_node.epistemic_status == EpistemicStatus.ACTIVE

    # Create a new MemoryGraph instance pointing at the same storage directory
    mg2 = MemoryGraph(storage_dir=storage)
    loaded_node = mg2.node(habit_node.id)

    assert loaded_node is not None
    assert loaded_node.id == habit_node.id
    assert loaded_node.label == habit_text
    assert loaded_node.type == NodeType.HABIT
    assert loaded_node.epistemic_status == EpistemicStatus.ACTIVE
    assert loaded_node.is_active() is True
    assert loaded_node.metadata.get("source_receipt_id") == 1

    # Active nodes in mg2 includes the habit
    active = mg2.active_nodes()
    assert any(n.id == habit_node.id for n in active)

