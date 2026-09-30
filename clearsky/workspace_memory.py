"""One memory graph and router per workspace, shared by everyone using it.

With several people signed in, each can be in a different workspace. A single
global graph would be swapped under one user's request when another switched,
so each workspace keeps its own graph (ADRs, notes, learned habits) in its own
SQLite file, and every router shares one Verdict engine (the weights load once).
"""

from __future__ import annotations
import hashlib
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from aegis.core.ingestion import WorkspaceIngestor
from aegis.core.models import NodeType
from aegis.system1.graph import MemoryGraph
from aegis.system1.router import Router, scoped_exclusions


@dataclass
class WorkspaceHandle:
    root: Path
    graph: MemoryGraph
    router: Router


def workspace_slug(root: Path) -> str:
    """Readable and collision-free: '<folder>-<hash of full path>'."""
    root = Path(root).resolve()
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", root.name) or "root"
    return f"{name}-{hashlib.sha256(str(root).encode()).hexdigest()[:8]}"


def ingest_workspace(graph: MemoryGraph, root: Path) -> None:
    """Replace the graph's ADRs and notes with the workspace's current files, keeping habits."""
    habits = [n for n in graph.all_nodes() if n.type == NodeType.HABIT]
    nodes, edges = WorkspaceIngestor.ingest_adrs(root)
    graph.replace_corpus(nodes, edges)
    for habit in habits:
        graph.upsert_node(habit)
    if (root / "notes").is_dir():
        for note in WorkspaceIngestor.ingest_markdown_vault(root / "notes"):
            graph.upsert_node(note)


def copy_habits(source: MemoryGraph, target: MemoryGraph, root: Path) -> int:
    """Copy habits learned for root (and untagged ones, which apply everywhere)."""
    copied = 0
    for habit in source.all_nodes():
        if habit.type == NodeType.HABIT and habit.metadata.get("workspace") in (None, str(root)):
            target.upsert_node(habit)
            copied += 1
    return copied


class WorkspaceMemory:
    def __init__(self, storage_dir: Path, config, engine=None, legacy_storage: Optional[Path] = None):
        """legacy_storage: a directory holding the old single memory.sqlite whose habits
        are copied into each workspace the first time that workspace is opened."""
        self.storage_dir = Path(storage_dir)
        self.config = config
        self._engine = engine
        self.legacy_storage = Path(legacy_storage) if legacy_storage else None
        self._handles: Dict[Path, WorkspaceHandle] = {}
        self._lock = threading.RLock()

    @property
    def engine(self):
        return self._engine

    def _router(self, graph: MemoryGraph) -> Router:
        router = Router(graph=graph, config=self.config, engine=self._engine)
        if self._engine is None:
            self._engine = router.engine  # first router loads Verdict; the rest reuse it
        return router

    def get(self, root: Path) -> WorkspaceHandle:
        root = Path(root).resolve()
        with self._lock:
            handle = self._handles.get(root)
            if handle is None:
                store = self.storage_dir / workspace_slug(root)
                is_new = not (store / "memory.sqlite").exists()
                graph = MemoryGraph(storage_dir=store)
                if is_new and self.legacy_storage and (self.legacy_storage / "memory.sqlite").exists():
                    copy_habits(MemoryGraph(storage_dir=self.legacy_storage), graph, root)
                ingest_workspace(graph, root)
                handle = WorkspaceHandle(root, graph, self._router(graph))
                self._handles[root] = handle
                scoped_exclusions(root)  # warm the scan cache so the first request is fast
            return handle

    def reload(self, root: Path) -> WorkspaceHandle:
        """Re-read the workspace's ADRs and notes (after edits); habits are kept."""
        root = Path(root).resolve()
        with self._lock:
            handle = self._handles.get(root)
            if handle is None:
                return self.get(root)
            ingest_workspace(handle.graph, root)
            handle.router = self._router(handle.graph)
            scoped_exclusions(root)
            return handle

    def forget(self, root: Path, delete_storage: bool = False) -> None:
        """Drop a workspace from memory (and optionally its database), e.g. on demo reset."""
        root = Path(root).resolve()
        with self._lock:
            self._handles.pop(root, None)
            if delete_storage:
                db = self.storage_dir / workspace_slug(root) / "memory.sqlite"
                for suffix in ("", "-wal", "-shm"):
                    path = Path(f"{db}{suffix}")
                    if path.exists():
                        path.unlink()

    def roots(self) -> List[Path]:
        with self._lock:
            return list(self._handles)
