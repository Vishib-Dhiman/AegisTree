from pathlib import Path

from aegis.core.watcher import WorkspaceWatcher


def make_workspace(root: Path) -> Path:
    (root / "docs" / "adr").mkdir(parents=True)
    (root / "docs" / "adr" / "001-first.md").write_text("# ADR-001: First\n- Status: Accepted\n")
    return root


def test_detects_added_modified_removed(tmp_path: Path):
    root = make_workspace(tmp_path / "ws")
    calls = []
    w = WorkspaceWatcher(get_root=lambda: root, on_change=calls.append)
    assert w.poll_once() is None  # first poll only takes a baseline

    new_adr = root / "docs" / "adr" / "002-second.md"
    new_adr.write_text("# ADR-002: Second\n- Status: Accepted\n")
    event = w.poll_once()
    assert event.added == ["docs/adr/002-second.md"]
    assert len(calls) == 1

    new_adr.write_text("# ADR-002: Second\n- Status: Superseded\n")
    assert w.poll_once().modified == ["docs/adr/002-second.md"]

    new_adr.unlink()
    assert w.poll_once().removed == ["docs/adr/002-second.md"]
    assert w.poll_once() is None  # nothing changed since
    assert [e.seq for e in w.events_since(0)] == [1, 2, 3]
    assert [e.seq for e in w.events_since(2)] == [3]


def test_notes_are_watched_and_other_files_are_not(tmp_path: Path):
    root = make_workspace(tmp_path / "ws")
    (root / "notes").mkdir()
    w = WorkspaceWatcher(get_root=lambda: root, on_change=lambda c: None)
    w.poll_once()
    (root / "src.py").write_text("x = 1\n")
    assert w.poll_once() is None
    (root / "notes" / "owners.md").write_text("# Owners\n")
    assert w.poll_once().added == ["notes/owners.md"]


def test_paused_without_workspace_and_rebaselines_on_switch(tmp_path: Path):
    a = make_workspace(tmp_path / "a")
    b = make_workspace(tmp_path / "b")
    current = {"root": a}
    calls = []
    w = WorkspaceWatcher(get_root=lambda: current["root"], on_change=calls.append)
    w.poll_once()

    current["root"] = None  # No-workspace mode
    (a / "docs" / "adr" / "009-x.md").write_text("# ADR-009: X\n")
    assert w.poll_once() is None

    current["root"] = b  # switching workspaces is not a change event
    assert w.poll_once() is None
    assert calls == []


def test_reload_failure_is_recorded_and_watching_continues(tmp_path: Path):
    root = make_workspace(tmp_path / "ws")

    def boom(changes):
        raise RuntimeError("bad ADR")

    w = WorkspaceWatcher(get_root=lambda: root, on_change=boom)
    w.poll_once()
    (root / "docs" / "adr" / "002-bad.md").write_text("#\n")
    event = w.poll_once()
    assert event.error == "bad ADR"
    (root / "docs" / "adr" / "003-ok.md").write_text("# ADR-003: Ok\n")
    assert w.poll_once().added == ["docs/adr/003-ok.md"]
