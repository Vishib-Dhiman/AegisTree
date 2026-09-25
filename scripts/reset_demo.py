#!/usr/bin/env python3
"""Resets demo_vault and rebuilds .aegis/memory.sqlite from scratch."""

import sys
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from aegis.core.ingestion import WorkspaceIngestor
from aegis.demo import seed_vault
from aegis.system1.graph import MemoryGraph


def reset():
    vault_path = root_dir / "demo_vault"
    storage_path = root_dir / ".aegis"
    storage_path.mkdir(parents=True, exist_ok=True)

    # 1. Restore demo_vault files
    seed_vault.write(vault_path)

    # 2. Reset database
    db_file = storage_path / "memory.sqlite"
    for extra in ["", "-wal", "-shm"]:
        p = Path(f"{db_file}{extra}")
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass

    graph = MemoryGraph(storage_dir=storage_path)
    nodes, edges = WorkspaceIngestor.ingest_adrs(vault_path)
    note_nodes = WorkspaceIngestor.ingest_markdown_vault(vault_path / "notes")
    graph.replace_corpus(nodes, edges)
    for n in note_nodes:
        graph.upsert_node(n)

    print("reset ok")


if __name__ == "__main__":
    reset()
