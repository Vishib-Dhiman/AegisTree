"""Temporal SQLite and NetworkX Memory Graph for AegisTree.
Implements nodes, bi-temporal edges, habits, and receipts storage.
"""

from __future__ import annotations
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import networkx as nx

from aegis.core.models import BiTemporalEdge, EpistemicStatus, GraphNode, NodeType


class MemoryGraph:
    """Persistent storage backed by SQLite and an in-memory NetworkX directed graph."""

    def __init__(self, storage_dir: Union[str, Path] = ".aegis"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.storage_dir / "memory.sqlite"
        self._init_db()
        self._nx_graph = self.rebuild_networkx()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS nodes (
                  id TEXT PRIMARY KEY,
                  type TEXT NOT NULL,
                  label TEXT NOT NULL,
                  description TEXT NOT NULL,
                  epistemic_status TEXT NOT NULL,
                  metadata_json TEXT NOT NULL,
                  tags_json TEXT NOT NULL,
                  valid_from TEXT,
                  superseded_at TEXT,
                  required_json TEXT NOT NULL,
                  forbidden_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS edges (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  source TEXT NOT NULL,
                  target TEXT NOT NULL,
                  relation TEXT NOT NULL,
                  recorded_at TEXT NOT NULL,
                  valid_from TEXT NOT NULL,
                  deprecated_at TEXT
                );

                CREATE TABLE IF NOT EXISTS receipts (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  created_at TEXT NOT NULL,
                  prompt TEXT NOT NULL,
                  task_type TEXT NOT NULL,
                  policy_ids_json TEXT NOT NULL,
                  decision_source TEXT NOT NULL,
                  verdict_json TEXT NOT NULL,
                  leaf_text TEXT NOT NULL,
                  baseline_text TEXT NOT NULL,
                  model_output TEXT NOT NULL,
                  approved_output TEXT NOT NULL,
                  habit_id TEXT
                );
                """
            )

    @staticmethod
    def _parse_dt(val: Optional[str]) -> Optional[datetime]:
        if not val:
            return None
        dt = datetime.fromisoformat(val)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    def _row_to_node(self, row: sqlite3.Row) -> GraphNode:
        return GraphNode(
            id=row["id"],
            type=NodeType(row["type"]),
            label=row["label"],
            description=row["description"],
            epistemic_status=EpistemicStatus(row["epistemic_status"]),
            metadata=json.loads(row["metadata_json"]),
            tags=json.loads(row["tags_json"]),
            valid_from=self._parse_dt(row["valid_from"]),
            superseded_at=self._parse_dt(row["superseded_at"]),
            required_literals=json.loads(row["required_json"]),
            forbidden_literals=json.loads(row["forbidden_json"]),
        )

    def _row_to_edge(self, row: sqlite3.Row) -> BiTemporalEdge:
        return BiTemporalEdge(
            source=row["source"],
            target=row["target"],
            relation=row["relation"],
            system_time=self._parse_dt(row["recorded_at"]) or datetime.now(timezone.utc),
            valid_from=self._parse_dt(row["valid_from"]) or datetime.now(timezone.utc),
            deprecated_at=self._parse_dt(row["deprecated_at"]),
        )

    def replace_corpus(self, nodes: List[GraphNode], edges: List[BiTemporalEdge]) -> None:
        """Replace nodes and edges with the given corpus. Does NOT delete receipts."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM nodes;")
            conn.execute("DELETE FROM edges;")
            for n in nodes:
                conn.execute(
                    """
                    INSERT INTO nodes (
                      id, type, label, description, epistemic_status,
                      metadata_json, tags_json, valid_from, superseded_at,
                      required_json, forbidden_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        n.id,
                        n.type.value if hasattr(n.type, "value") else str(n.type),
                        n.label,
                        n.description,
                        n.epistemic_status.value if hasattr(n.epistemic_status, "value") else str(n.epistemic_status),
                        json.dumps(n.metadata),
                        json.dumps(n.tags),
                        n.valid_from.isoformat() if n.valid_from else None,
                        n.superseded_at.isoformat() if n.superseded_at else None,
                        json.dumps(n.required_literals),
                        json.dumps(n.forbidden_literals),
                    ),
                )
            for e in edges:
                conn.execute(
                    """
                    INSERT INTO edges (
                      source, target, relation, recorded_at, valid_from, deprecated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        e.source,
                        e.target,
                        e.relation,
                        e.system_time.isoformat(),
                        e.valid_from.isoformat(),
                        e.deprecated_at.isoformat() if e.deprecated_at else None,
                    ),
                )
        self.rebuild_networkx()

    def upsert_node(self, node: GraphNode) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO nodes (
                  id, type, label, description, epistemic_status,
                  metadata_json, tags_json, valid_from, superseded_at,
                  required_json, forbidden_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    node.id,
                    node.type.value if hasattr(node.type, "value") else str(node.type),
                    node.label,
                    node.description,
                    node.epistemic_status.value if hasattr(node.epistemic_status, "value") else str(node.epistemic_status),
                    json.dumps(node.metadata),
                    json.dumps(node.tags),
                    node.valid_from.isoformat() if node.valid_from else None,
                    node.superseded_at.isoformat() if node.superseded_at else None,
                    json.dumps(node.required_literals),
                    json.dumps(node.forbidden_literals),
                ),
            )
        self._nx_graph.add_node(node.id, data=node)

    def upsert_edge(self, edge: BiTemporalEdge) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO edges (
                  source, target, relation, recorded_at, valid_from, deprecated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    edge.source,
                    edge.target,
                    edge.relation,
                    edge.system_time.isoformat(),
                    edge.valid_from.isoformat(),
                    edge.deprecated_at.isoformat() if edge.deprecated_at else None,
                ),
            )
        self._nx_graph.add_edge(edge.source, edge.target, relation=edge.relation, edge_data=edge)

    def all_nodes(self) -> List[GraphNode]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM nodes;").fetchall()
            return [self._row_to_node(r) for r in rows]

    def all_edges(self) -> List[BiTemporalEdge]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM edges;").fetchall()
            return [self._row_to_edge(r) for r in rows]

    def active_nodes(self, at: Optional[datetime] = None) -> List[GraphNode]:
        nodes = self.all_nodes()
        return [n for n in nodes if n.is_active(at)]

    def node(self, node_id: str) -> Optional[GraphNode]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM nodes WHERE id = ?;", (node_id,)).fetchone()
            if row:
                return self._row_to_node(row)
        return None

    def rebuild_networkx(self) -> nx.DiGraph:
        g = nx.DiGraph()
        for n in self.all_nodes():
            g.add_node(n.id, data=n)
        for e in self.all_edges():
            g.add_edge(e.source, e.target, relation=e.relation, edge_data=e)
        self._nx_graph = g
        return g

    def successors(self, node_id: str, relation: Optional[str] = None) -> List[GraphNode]:
        if node_id not in self._nx_graph:
            return []
        results: List[GraphNode] = []
        for succ in self._nx_graph.successors(node_id):
            edge_data = self._nx_graph.get_edge_data(node_id, succ) or {}
            if relation is None or edge_data.get("relation") == relation:
                target_node = self.node(succ)
                if target_node:
                    results.append(target_node)
        return results

    def add_habit(
        self,
        text: str,
        source_receipt_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> GraphNode:
        now = datetime.now(timezone.utc)
        habit_id = f"habit:{uuid.uuid4().hex[:8]}"
        tags = [tok for tok in re.findall(r"\b[a-z0-9_]+\b", text.lower()) if len(tok) >= 2]
        meta: Dict[str, Any] = {"source_receipt_id": source_receipt_id} if source_receipt_id is not None else {}
        if metadata:
            meta.update(metadata)

        # Bi-temporal supersession: If a habit with the same key already exists, supersede it
        key = meta.get("key")
        if not key:
            if "retries=" in text:
                key = "retries"
            elif "timeout_s=" in text:
                key = "timeout_s"
            elif "key_id=" in text:
                key = "key_id"
            if key:
                meta["key"] = key

        if key:
            for active in self.active_nodes(now):
                if active.type == NodeType.HABIT:
                    active_key = active.metadata.get("key")
                    if not active_key:
                        if "retries=" in active.label:
                            active_key = "retries"
                        elif "timeout_s=" in active.label:
                            active_key = "timeout_s"
                        elif "key_id=" in active.label:
                            active_key = "key_id"
                    if active_key == key and active.id != habit_id:
                        active.superseded_at = now
                        active.epistemic_status = EpistemicStatus.SUPERSEDED
                        self.upsert_node(active)
                        edge = BiTemporalEdge(
                            source=habit_id,
                            target=active.id,
                            relation="supersedes",
                            system_time=now,
                            valid_from=now,
                        )
                        self.upsert_edge(edge)

        node = GraphNode(
            id=habit_id,
            type=NodeType.HABIT,
            label=text,
            description=text,
            epistemic_status=EpistemicStatus.ACTIVE,
            valid_from=now,
            tags=tags,
            metadata=meta,
        )
        self.upsert_node(node)
        return node

    def add_receipt(
        self,
        prompt: str,
        task_type: str,
        policy_ids: List[str],
        decision_source: str,
        verdict_data: Dict[str, Any],
        leaf_text: str,
        baseline_text: str,
        model_output: str,
        approved_output: str,
        habit_id: Optional[str] = None,
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO receipts (
                  created_at, prompt, task_type, policy_ids_json, decision_source,
                  verdict_json, leaf_text, baseline_text, model_output,
                  approved_output, habit_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    prompt,
                    task_type,
                    json.dumps(policy_ids),
                    decision_source,
                    json.dumps(verdict_data),
                    leaf_text,
                    baseline_text,
                    model_output,
                    approved_output,
                    habit_id,
                ),
            )
            return cursor.lastrowid

    def recent_receipts(self, limit: int = 10) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM receipts ORDER BY id DESC LIMIT ?;", (limit,)
            ).fetchall()
            results = []
            for r in rows:
                results.append(
                    {
                        "id": r["id"],
                        "created_at": r["created_at"],
                        "prompt": r["prompt"],
                        "task_type": r["task_type"],
                        "policy_ids": json.loads(r["policy_ids_json"]),
                        "decision_source": r["decision_source"],
                        "verdict": json.loads(r["verdict_json"]),
                        "leaf_text": r["leaf_text"],
                        "baseline_text": r["baseline_text"],
                        "model_output": r["model_output"],
                        "approved_output": r["approved_output"],
                        "habit_id": r["habit_id"],
                    }
                )
            return results
