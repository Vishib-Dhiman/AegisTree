"""FastMCP stdio server wrapper for AegisTree tools (optional)."""

import sys
from pathlib import Path

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


def main():
    if not HAS_FASTMCP:
        print("FastMCP is not installed. The demo tools run inside the web app at 127.0.0.1:8080.")
        sys.exit(0)

    mcp = FastMCP("AegisTree Sovereign Tools")

    @mcp.tool()
    def search_decisions_tool(query: str) -> dict:
        from aegis.core.config import config_manager
        from aegis.system1.graph import MemoryGraph
        graph = MemoryGraph(storage_dir=config_manager.config.storage_dir)
        return search_decisions(graph, query)

    @mcp.tool()
    def propose_patch_tool(prompt: str, code: str) -> dict:
        from aegis.core.config import config_manager
        from aegis.system1.graph import MemoryGraph
        from aegis.system1.router import Router
        cfg = config_manager.config
        graph = MemoryGraph(storage_dir=cfg.storage_dir)
        router = Router(graph=graph, config=cfg)
        route = router.route(prompt, workspace_root=cfg.workspace_root)
        return propose_patch(route, code, workspace_root=cfg.workspace_root, prompt=prompt)

    @mcp.tool()
    def apply_patch_tool(prompt: str, approved_code: str, approved: bool) -> dict:
        from aegis.core.config import config_manager
        from aegis.system1.graph import MemoryGraph
        from aegis.system1.router import Router
        cfg = config_manager.config
        graph = MemoryGraph(storage_dir=cfg.storage_dir)
        router = Router(graph=graph, config=cfg)
        route = router.route(prompt, workspace_root=cfg.workspace_root)
        return apply_patch(graph, route, approved_code, approved, workspace_root=cfg.workspace_root, prompt=prompt)

    mcp.run()


if __name__ == "__main__":
    main()
