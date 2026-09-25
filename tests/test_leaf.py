from datetime import datetime, timezone
from pathlib import Path

from aegis.core.ingestion import WorkspaceIngestor
from aegis.system1.graph import MemoryGraph
from aegis.system1.leaf import compile_leaf, estimate_tokens
from aegis.system1.router import Router
from aegis.system2.prompt import compile_baseline, extract_code, is_code_parseable


def test_leaf_and_baseline_compilation(tmp_path: Path, test_vault: Path):
    storage = tmp_path / ".aegis"
    graph = MemoryGraph(storage_dir=storage)
    nodes, edges = WorkspaceIngestor.ingest_adrs(test_vault)
    graph.replace_corpus(nodes, edges)

    router = Router(graph=graph)
    prompt = "Add a persist_session_token function that stores the session token using our current vault standard."
    route = router.route(
        prompt=prompt,
        workspace_root=test_vault,
        now=datetime(2026, 9, 24, tzinfo=timezone.utc),
    )

    leaf = compile_leaf(
        route=route,
        graph=graph,
        prompt=prompt,
        workspace_root=test_vault,
    )

    # Implement prompt's leaf contains kek-2026, aegis_seal, timeout_s=5.0
    assert "kek-2026" in leaf
    assert "aegis_seal" in leaf
    assert "timeout_s=5.0" in leaf

    # legacy_wrap appears ONLY inside a FORBIDDEN line
    lines_with_legacy_wrap = [
        line for line in leaf.splitlines()
        if "legacy_wrap" in line
    ]
    assert len(lines_with_legacy_wrap) == 1
    assert "FORBIDDEN IN PRODUCTION" in leaf
    assert lines_with_legacy_wrap[0].strip().startswith("- legacy_wrap")

    # Leaf does not contain the body of test_legacy_wrap.py
    assert "test_legacy_wrap_still_covers_backup_jobs" not in leaf

    # Leaf does not contain export_session_blob
    assert "export_session_blob" not in leaf

    # Baseline does contain export_session_blob and does contain ADR-014
    baseline = compile_baseline(
        prompt=prompt,
        workspace_root=test_vault,
    )
    assert "export_session_blob" in baseline
    assert "ADR-014" in baseline

    # Token estimate logic: 400-char text estimates 100
    sample_text = "x" * 400
    assert estimate_tokens(sample_text) == 100


def test_code_extraction():
    fenced = "Here is the code:\n```python\ndef persist_session_token(token: str) -> str:\n    return 'ok'\n```"
    code = extract_code(fenced)
    assert code == "def persist_session_token(token: str) -> str:\n    return 'ok'"
    assert is_code_parseable(code, "persist_session_token") is True
    assert is_code_parseable(code, "rotate_session_token") is False
