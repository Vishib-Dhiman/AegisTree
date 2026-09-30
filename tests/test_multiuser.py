"""Path safety and per-workspace memory for multi-user ClearSky.

The server module is imported only for its pure helpers; nothing here writes to
the real .aegis store (the full two-user flow is exercised by the smoke test).
"""

from pathlib import Path

import pytest
from fastapi import HTTPException

from aegis.core.config import SystemConfig
from aegis.core.models import NodeType
from aegis.demo import seed_vault
from aegis.system1.graph import MemoryGraph
from clearsky.workspace_memory import WorkspaceMemory, workspace_slug
from tests.test_policy_guard import ScriptedEngine


@pytest.fixture(scope="module")
def srv():
    import aegis.ui.server as srv
    return srv


@pytest.mark.parametrize("adr_id", [
    "../../../etc/passwd", "adr:../../x", "..%2F..%2Fx", "/etc/hosts", "a/b", "adr:.hidden", "x.md/../../y",
])
def test_adr_ids_cannot_escape_docs_adr(srv, test_vault: Path, adr_id):
    with pytest.raises(HTTPException) as ex:
        srv._adr_file(test_vault, adr_id)
    assert ex.value.status_code in (400, 404)
    if ex.value.status_code == 404:  # only a plain name inside docs/adr may reach the lookup
        assert "/" not in adr_id and ".." not in adr_id


def test_valid_adr_ids_resolve_inside_docs_adr(srv, test_vault: Path):
    path = srv._adr_file(test_vault, "adr:014-aegis-seal")
    assert path == (test_vault / "docs" / "adr" / "014-aegis-seal.md").resolve()
    new = srv._adr_file(test_vault, "030-new.md", must_exist=False)
    assert new.parent == (test_vault / "docs" / "adr").resolve()


def test_workspaces_limited_to_presets_and_allowed_roots(srv, monkeypatch, tmp_path: Path):
    assert srv._resolve_workspace("sqlalchemy") == (srv.PROJECT_ROOT / "repos" / "sqlalchemy").resolve()
    for outside in (str(Path.home()), "/etc", "../..", str(tmp_path)):
        with pytest.raises(HTTPException) as ex:
            srv._resolve_workspace(outside)
        assert ex.value.status_code == 403
    monkeypatch.setattr(srv.config_manager.config, "allowed_workspace_roots", [str(tmp_path)])
    inside = tmp_path / "team-repo"
    assert srv._resolve_workspace(str(inside)) == inside.resolve()


def test_each_workspace_has_its_own_memory_and_one_engine(tmp_path: Path):
    a, b = tmp_path / "a" / "demo_vault", tmp_path / "b" / "demo_vault"
    seed_vault.write(a)
    seed_vault.write(b)
    engine = ScriptedEngine()
    memory = WorkspaceMemory(tmp_path / "store", SystemConfig(), engine=engine)
    ha, hb = memory.get(a), memory.get(b)
    assert ha.graph is not hb.graph
    assert ha.router.engine is engine and hb.router.engine is engine
    assert workspace_slug(a) != workspace_slug(b)  # same folder name, different paths

    ha.graph.add_habit("Calls to aegis_seal must set retries=1.", metadata={"key": "k", "workspace": str(a.resolve())})
    assert not [n for n in hb.graph.all_nodes() if n.type == NodeType.HABIT]

    (a / "docs" / "adr" / "030-new.md").write_text("# ADR-030: New rule\n- Status: Accepted\n")
    memory.reload(a)
    ids = {n.id for n in ha.graph.all_nodes()}
    assert "adr:030-new" in ids
    assert [n for n in ha.graph.all_nodes() if n.type == NodeType.HABIT]  # habits survive reload
    assert "adr:030-new" not in {n.id for n in hb.graph.all_nodes()}


def test_habits_migrate_from_the_old_single_memory(tmp_path: Path):
    vault = tmp_path / "demo_vault"
    seed_vault.write(vault)
    legacy = MemoryGraph(storage_dir=tmp_path / "legacy")
    legacy.add_habit("Calls to aegis_seal must set retries=1.", metadata={"key": "k1", "workspace": str(vault.resolve())})
    legacy.add_habit("Calls to x must set y=2.", metadata={"key": "k2", "workspace": "/somewhere/else"})
    memory = WorkspaceMemory(tmp_path / "store", SystemConfig(), engine=ScriptedEngine(), legacy_storage=tmp_path / "legacy")
    labels = [n.label for n in memory.get(vault).graph.all_nodes() if n.type == NodeType.HABIT]
    assert labels == ["Calls to aegis_seal must set retries=1."]


def test_forget_with_storage_starts_clean(tmp_path: Path):
    vault = tmp_path / "demo_vault"
    seed_vault.write(vault)
    memory = WorkspaceMemory(tmp_path / "store", SystemConfig(), engine=ScriptedEngine())
    memory.get(vault).graph.add_habit("h", metadata={"key": "k"})
    memory.forget(vault, delete_storage=True)
    assert vault.resolve() not in memory.roots()
    assert not [n for n in memory.get(vault).graph.all_nodes() if n.type == NodeType.HABIT]


def _request(host: str, headers: dict):
    from starlette.requests import Request as StarletteRequest
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return StarletteRequest({"type": "http", "client": (host, 50000), "headers": raw})


def test_computer_access_is_local_only_even_through_a_tunnel(srv):
    assert srv._is_local(_request("127.0.0.1", {}))
    assert not srv._is_local(_request("192.168.0.20", {}))  # another device on the Wi-Fi
    # cloudflared connects from 127.0.0.1 but the visitor is on the internet
    assert not srv._is_local(_request("127.0.0.1", {"Cf-Connecting-Ip": "203.0.113.9", "Cf-Ray": "x"}))
    assert not srv._is_local(_request("127.0.0.1", {"X-Forwarded-For": "203.0.113.9"}))
