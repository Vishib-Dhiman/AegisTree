"""Offline Workspace Ingestion Pipeline for AegisTree.
Parses Architecture Decision Records (ADRs) and Markdown Notes into GraphNodes and BiTemporalEdges.
"""

from __future__ import annotations
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
from aegis.core.models import GraphNode, NodeType, EpistemicStatus, BiTemporalEdge


class ADRParser:
    """Parses Architecture Decision Records (ADRs) in markdown format."""

    TITLE_PATTERN = re.compile(r"^#\s+(?:\d+[\.\-\s]+)?(.+)$", re.MULTILINE)
    STATUS_PATTERN = re.compile(r"(?:Status|State):\s*([a-zA-Z\s\-]+)", re.IGNORECASE)
    DATE_PATTERN = re.compile(r"(?:Date|Effective):\s*(\d{4}-\d{2}-\d{2})", re.IGNORECASE)
    SUPERSEDES_PATTERN = re.compile(r"^[*-]?\s*(?:Supersedes|Replaces|Deprecates):\s*(.+)$", re.IGNORECASE | re.MULTILINE)
    TAGS_PATTERN = re.compile(r"^[*-]?\s*Tags:\s*(.+)$", re.IGNORECASE | re.MULTILINE)

    @classmethod
    def _extract_section_items(cls, content: str, header: str) -> List[str]:
        pattern = rf"^##\s+{re.escape(header)}\s*$(.*?)(?=^##\s+|\Z)"
        match = re.search(pattern, content, re.MULTILINE | re.DOTALL)
        if not match:
            return []
        items: List[str] = []
        for line in match.group(1).splitlines():
            line = line.strip()
            if line.startswith("- ") or line.startswith("* "):
                item = line[2:].strip()
                if item:
                    items.append(item)
        return items

    @classmethod
    def _extract_section_text(cls, content: str, header: str) -> str:
        pattern = rf"^##\s+{re.escape(header)}\s*$(.*?)(?=^##\s+|\Z)"
        match = re.search(pattern, content, re.MULTILINE | re.DOTALL)
        if not match:
            return ""
        return match.group(1).strip()

    @classmethod
    def parse_file(cls, filepath: Path) -> Optional[Tuple[GraphNode, List[BiTemporalEdge]]]:
        if not filepath.exists() or filepath.suffix != ".md":
            return None

        content = filepath.read_text(encoding="utf-8", errors="ignore")

        # Title
        title_match = cls.TITLE_PATTERN.search(content)
        title = title_match.group(1).strip() if title_match else filepath.stem

        # Status
        status_match = cls.STATUS_PATTERN.search(content)
        raw_status = status_match.group(1).strip().lower() if status_match else "accepted"

        if "superseded" in raw_status:
            epistemic_status = EpistemicStatus.SUPERSEDED
        elif "accepted" in raw_status:
            epistemic_status = EpistemicStatus.ACTIVE
        elif "deprecat" in raw_status or "abandoned" in raw_status:
            epistemic_status = EpistemicStatus.DEPRECATED
        elif "hypothesis" in raw_status or "proposed" in raw_status:
            epistemic_status = EpistemicStatus.HYPOTHESIS
        else:
            epistemic_status = EpistemicStatus.ACTIVE

        # Date
        date_match = cls.DATE_PATTERN.search(content)
        valid_from = (
            datetime.strptime(date_match.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if date_match
            else datetime.now(timezone.utc)
        )

        # Tags
        tags: List[str] = []
        tags_match = cls.TAGS_PATTERN.search(content)
        if tags_match:
            tags = [t.strip().lower() for t in tags_match.group(1).split(",") if t.strip()]

        # Required & Forbidden literals
        required_literals = cls._extract_section_items(content, "Required")
        raw_forbidden = cls._extract_section_items(content, "Forbidden")
        forbidden_literals = [f for f in raw_forbidden if f.lower() != "none"]

        # Decision description (Decision section only, max 400 chars)
        decision_text = cls._extract_section_text(content, "Decision")
        description = decision_text[:400] if decision_text else content[:400].strip()

        node_id = f"adr:{filepath.stem}"
        node = GraphNode(
            id=node_id,
            type=NodeType.ARCHITECTURE_DECISION,
            label=title,
            description=description,
            epistemic_status=epistemic_status,
            tags=tags,
            valid_from=valid_from,
            required_literals=required_literals,
            forbidden_literals=forbidden_literals,
            metadata={
                "source_file": str(filepath),
                "raw_status": raw_status,
                "parsed_date": valid_from.isoformat(),
            },
        )

        edges: List[BiTemporalEdge] = []
        supersedes_match = cls.SUPERSEDES_PATTERN.search(content)
        if supersedes_match:
            superseded_target = supersedes_match.group(1).strip()
            edge = BiTemporalEdge(
                source=node_id,
                target=superseded_target,
                relation="supersedes",
                system_time=datetime.now(timezone.utc),
                valid_from=valid_from,
                deprecated_at=None,
            )
            edges.append(edge)

        return node, edges


def apply_supersession(nodes: List[GraphNode], edges: List[BiTemporalEdge]) -> None:
    """Second pass resolving supersedes edges and marking superseded targets."""
    nodes_by_id = {node.id: node for node in nodes}
    for edge in edges:
        if edge.relation == "supersedes":
            source_node = nodes_by_id.get(edge.source)
            target_token = edge.target

            # Target token matching: e.g. target token 'ADR-003' matches unique node whose id contains '003-'
            target_node = None
            digit_match = re.search(r"\d+", target_token)
            if digit_match:
                prefix = f"{digit_match.group(0)}-"
                matches = [n for n in nodes if prefix in n.id]
                if len(matches) == 1:
                    target_node = matches[0]

            if target_node is None:
                cleaned = re.sub(r"[^a-zA-Z0-9_-]", "", target_token).lower()
                matches = [n for n in nodes if n.id == target_token or n.id == f"adr:{cleaned}"]
                if len(matches) == 1:
                    target_node = matches[0]

            if target_node is not None:
                edge.target = target_node.id
                target_node.epistemic_status = EpistemicStatus.SUPERSEDED
                if source_node:
                    target_node.superseded_at = source_node.valid_from
                    for lit in source_node.forbidden_literals:
                        if lit not in target_node.forbidden_literals:
                            target_node.forbidden_literals.append(lit)
                    for lit in target_node.required_literals:
                        if lit not in target_node.forbidden_literals:
                            target_node.forbidden_literals.append(lit)
                edge.deprecated_at = None
            else:
                edge.metadata["unresolved_target"] = True


def get_superseded_closure(
    active_policy_ids: List[str],
    nodes: List[GraphNode],
    edges: List[BiTemporalEdge],
) -> List[GraphNode]:
    """For every id in active_policy_ids, follow supersedes edges to their targets."""
    node_map = {n.id: n for n in nodes}
    negative_nodes: List[GraphNode] = []
    seen = set()
    for policy_id in active_policy_ids:
        for edge in edges:
            if edge.source == policy_id and edge.relation == "supersedes":
                target = node_map.get(edge.target)
                if target and target.id not in seen:
                    seen.add(target.id)
                    negative_nodes.append(target)
    return negative_nodes


class WorkspaceIngestor:
    """Scans workspace directories and compiles the initial knowledge nodes."""

    @classmethod
    def ingest_adrs(cls, root_dir: Path) -> Tuple[List[GraphNode], List[BiTemporalEdge]]:
        nodes: List[GraphNode] = []
        edges: List[BiTemporalEdge] = []

        adr_dirs = [
            root_dir / "docs" / "adr",
            root_dir / "adr",
            root_dir / "docs" / "decisions",
        ]

        for d in adr_dirs:
            if d.exists() and d.is_dir():
                for md_file in sorted(d.glob("*.md")):
                    res = ADRParser.parse_file(md_file)
                    if res:
                        node, new_edges = res
                        nodes.append(node)
                        edges.extend(new_edges)

        apply_supersession(nodes, edges)
        return nodes, edges

    @classmethod
    def ingest_markdown_vault(cls, vault_dir: Path) -> List[GraphNode]:
        """Parses local Obsidian/Markdown vaults extracting tags and wikilinks."""
        nodes: List[GraphNode] = []
        if not vault_dir.exists() or not vault_dir.is_dir():
            return nodes

        wikilink_pattern = re.compile(r"\[\[([^\]]+)\]\]")
        tag_pattern = re.compile(r"#([a-zA-Z0-9_\-\/]+)")

        for md_file in sorted(vault_dir.rglob("*.md")):
            try:
                content = md_file.read_text(encoding="utf-8", errors="ignore")
                wikilinks = wikilink_pattern.findall(content)
                tags = tag_pattern.findall(content)

                node = GraphNode(
                    id=f"note:{md_file.stem}",
                    type=NodeType.PROJECT_STATE,
                    label=md_file.stem.replace("-", " ").replace("_", " ").title(),
                    description=content[:300].strip(),
                    epistemic_status=EpistemicStatus.ACTIVE,
                    valid_from=datetime.now(timezone.utc),
                    metadata={"source_file": str(md_file), "wikilinks": wikilinks},
                    tags=tags,
                )
                nodes.append(node)
            except Exception:
                continue

        return nodes
