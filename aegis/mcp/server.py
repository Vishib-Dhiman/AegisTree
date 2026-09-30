"""FastMCP stdio server exposing ClearSky's governance tools to MCP clients.

Run with:  .venv/bin/python -m aegis.mcp.server [--workspace PATH]
The tools use the same retrieval, bans and human-approval gate as the web app.
The server keeps its own memory for the workspace it serves (the web app's
memory follows whatever workspace its UI switched to), and starts with the
habits the web app learned for that workspace.
"""

import sys
from pathlib import Path
from typing import Optional, Union

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

try:
    from fastmcp import FastMCP
    HAS_FASTMCP = True
except ImportError:
    HAS_FASTMCP = False

from aegis.mcp.tools import apply_patch, propose_patch, search_decisions


def build_server(
    graph=None,
    router=None,
    workspace_root: Optional[Union[str, Path]] = None,
    threshold: Optional[float] = None,
) -> "FastMCP":
    """The MCP server. Arguments default to the app's config; tests pass their own.

    One graph and router are shared by every tool call, so the Verdict weights
    load once instead of on each call.
    """
    from aegis.core.config import config_manager
    from aegis.system1.graph import MemoryGraph
    from aegis.system1.router import Router

    cfg = config_manager.config
    state = {
        "graph": graph,
        "router": router,
        "root": workspace_root or cfg.workspace_root,
        "threshold": threshold if threshold is not None else cfg.system1_retrieval_threshold,
    }

    def env():
        if state["graph"] is None:
            state["graph"] = _workspace_graph(Path(state["root"]), Path(cfg.storage_dir))
        if state["router"] is None:
            state["router"] = Router(graph=state["graph"], config=cfg)
        return state["graph"], state["router"], state["root"]

    mcp = FastMCP("ClearSky Governance Tools")

    @mcp.tool(name="search_decisions")
    def search_decisions_tool(query: str) -> dict:
        """Which architecture decisions govern a request, and which literals they ban."""
        graph, router, root = env()
        return search_decisions(graph, query, engine=router.engine, workspace_root=root, threshold=state["threshold"])

    @mcp.tool(name="propose_patch")
    def propose_patch_tool(prompt: str, code: str) -> dict:
        """Diff a proposed function against the workspace and report banned literals. Writes nothing."""
        graph, router, root = env()
        route = router.route(prompt, workspace_root=root)
        return propose_patch(route, code, workspace_root=root, prompt=prompt)

    @mcp.tool(name="apply_patch")
    def apply_patch_tool(prompt: str, approved_code: str, approved: bool) -> dict:
        """Write an approved patch after syntax, path and ban checks; learns habits from edits."""
        graph, router, root = env()
        route = router.route(prompt, workspace_root=root)
        return apply_patch(graph, route, approved_code, approved, workspace_root=root, prompt=prompt)

    return mcp


def _workspace_graph(root: Path, storage_dir: Path):
    """A memory graph for `root` alone: its ADRs and notes, plus the habits the
    web app learned there (untagged habits apply everywhere, as in the app)."""
    from aegis.core.ingestion import WorkspaceIngestor
    from aegis.core.models import NodeType
    from aegis.system1.graph import MemoryGraph

    root = root.resolve()
    graph = MemoryGraph(storage_dir=storage_dir / "mcp" / root.name)
    nodes, edges = WorkspaceIngestor.ingest_adrs(root)
    graph.replace_corpus(nodes, edges)
    if (root / "notes").is_dir():
        for note in WorkspaceIngestor.ingest_markdown_vault(root / "notes"):
            graph.upsert_node(note)
    shared = storage_dir / "memory.sqlite"
    if shared.exists():
        for habit in MemoryGraph(storage_dir=storage_dir).all_nodes():
            if habit.type == NodeType.HABIT and habit.metadata.get("workspace") in (None, str(root)):
                graph.upsert_node(habit)
    return graph


def main():
    import argparse

    if not HAS_FASTMCP:
        print("FastMCP is not installed: run `uv pip install fastmcp` (it is in requirements.txt).")
        sys.exit(1)
    parser = argparse.ArgumentParser(description="ClearSky governance tools over MCP (stdio)")
    parser.add_argument("--workspace", help="repository to govern (default: workspace_root from .aegis/config.json)")
    args = parser.parse_args()
    build_server(workspace_root=args.workspace).run()


if __name__ == "__main__":
    main()
