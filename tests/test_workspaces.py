"""Tests for real GitHub repository workspaces and ADR routing."""

from pathlib import Path
import pytest

from aegis.core.config import config_manager
from aegis.core.ingestion import WorkspaceIngestor
from aegis.demo import seed_vault
from aegis.system1.graph import MemoryGraph
from aegis.system1.router import Router
from aegis.system1.leaf import extract_function_source
from clearsky.targets import resolve_target


def test_real_repo_sync_and_ingestion(tmp_path):
    repos_dir = tmp_path / "repos"
    for r in ["sqlalchemy", "cryptography", "pydantic"]:
        (repos_dir / r).mkdir(parents=True, exist_ok=True)

    seed_vault.sync_real_repos(tmp_path)

    # SQLAlchemy
    sa_nodes, sa_edges = WorkspaceIngestor.ingest_adrs(repos_dir / "sqlalchemy")
    sa_ids = [n.id for n in sa_nodes]
    assert "adr:010-legacy-engine-execute" in sa_ids
    assert "adr:045-sqlalchemy-20" in sa_ids

    # Cryptography
    cr_nodes, cr_edges = WorkspaceIngestor.ingest_adrs(repos_dir / "cryptography")
    cr_ids = [n.id for n in cr_nodes]
    assert "adr:005-rsa-pkcs1v15" in cr_ids
    assert "adr:021-rsa-oaep" in cr_ids

    # Pydantic
    py_nodes, py_edges = WorkspaceIngestor.ingest_adrs(repos_dir / "pydantic")
    py_ids = [n.id for n in py_nodes]
    assert "adr:008-pydantic-v1" in py_ids
    assert "adr:032-pydantic-v2" in py_ids


def test_real_repo_target_extraction(tmp_path):
    repos_dir = tmp_path / "repos"
    for r in ["sqlalchemy", "cryptography", "pydantic"]:
        (repos_dir / r).mkdir(parents=True, exist_ok=True)

    seed_vault.sync_real_repos(tmp_path)

    # Target selection and extraction for SQLAlchemy
    _t = resolve_target("query audit records", repos_dir / "sqlalchemy")
    sa_path, sa_fn = _t.path, _t.function
    assert sa_fn == "query_audit_trail"
    assert "query_audit_trail" in extract_function_source(sa_path, sa_fn)

    # Target selection and extraction for Cryptography
    _t = resolve_target("encrypt with rsa oaep", repos_dir / "cryptography")
    cr_path, cr_fn = _t.path, _t.function
    assert cr_fn == "encrypt_rsa_payload"
    assert "encrypt_rsa_payload" in extract_function_source(cr_path, cr_fn)

    # Target selection and extraction for Pydantic
    _t = resolve_target("Implement serialize_vault_payload using our current Pydantic standard.", repos_dir / "pydantic")
    pd_path, pd_fn = _t.path, _t.function
    assert pd_fn == "serialize_vault_payload"
    assert "serialize_vault_payload" in extract_function_source(pd_path, pd_fn)


def test_real_repo_sovereign_refusals(tmp_path):
    repos_dir = tmp_path / "repos"
    for r in ["sqlalchemy", "cryptography", "pydantic"]:
        (repos_dir / r).mkdir(parents=True, exist_ok=True)

    seed_vault.sync_real_repos(tmp_path)
    config = config_manager.config

    # Test Cryptography refusal on PKCS1v15
    cr_dir = repos_dir / "cryptography"
    cr_graph = MemoryGraph(storage_dir=tmp_path / "cr_storage")
    nodes, edges = WorkspaceIngestor.ingest_adrs(cr_dir)
    cr_graph.replace_corpus(nodes, edges)
    cr_router = Router(graph=cr_graph, config=config)

    route_cr = cr_router.route("Implement encrypt_rsa_payload using PKCS1v15 padding because it is simpler.", workspace_root=cr_dir)
    assert route_cr.status == "blocked"
    assert route_cr.blocking_policy_id == "adr:021-rsa-oaep"

    # Test SQLAlchemy refusal on engine.execute
    sa_dir = repos_dir / "sqlalchemy"
    sa_graph = MemoryGraph(storage_dir=tmp_path / "sa_storage")
    nodes, edges = WorkspaceIngestor.ingest_adrs(sa_dir)
    sa_graph.replace_corpus(nodes, edges)
    sa_router = Router(graph=sa_graph, config=config)

    route_sa = sa_router.route("Query audit records directly with engine.execute for quick results.", workspace_root=sa_dir)
    assert route_sa.status == "blocked"
    assert route_sa.blocking_policy_id == "adr:045-sqlalchemy-20"


def test_eyecite_workspace_ingestion_targets_and_refusal(tmp_path):
    ey_dir = tmp_path / "repos" / "eyecite"
    ey_dir.mkdir(parents=True)
    seed_vault.sync_real_repos(tmp_path)

    nodes, edges = WorkspaceIngestor.ingest_adrs(ey_dir)
    by_id = {n.id: n for n in nodes}
    assert by_id["adr:060-uniform-neutral-citation"].is_active()
    assert not by_id["adr:054-vendor-reporter-citations"].is_active()
    assert not by_id["adr:057-raw-party-names"].is_active()

    target = resolve_target("Implement format_case_citation using our current citation standard.", ey_dir)
    assert target.function == "format_case_citation"
    assert "format_case_citation" in extract_function_source(target.path, target.function)

    graph = MemoryGraph(storage_dir=tmp_path / "ey_storage")
    graph.replace_corpus(nodes, edges)
    router = Router(graph=graph, config=config_manager.config)
    route = router.route("Format the case citation with westlaw_cite because clerks are used to it.", workspace_root=ey_dir)
    assert route.status == "blocked"
    assert route.blocking_policy_id == "adr:060-uniform-neutral-citation"
