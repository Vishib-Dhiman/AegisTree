"""Leaf Context Compiler.
Builds the minimal, strictly bounded prompt for System 2 containing active decisions,
closure bans, habits, and only the target function to edit (chosen by clearsky.targets).
"""

from __future__ import annotations
import ast
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple, Union

from aegis.core.models import GraphNode
from aegis.system1.graph import MemoryGraph
from aegis.system1.router import RouteResult
from clearsky.targets import helper_signatures, resolve_target


def estimate_tokens(text: str) -> int:
    """Estimator: max(1, (len(text) + 3) // 4) with label 'chars/4 estimate'."""
    return max(1, (len(text) + 3) // 4)


def route_target(route: RouteResult, root: Path, prompt: str = "") -> Tuple[Path, str, bool, str]:
    """(file, function, exists, relative path) the request edits, as System 1 chose it.
    Routes built without a target (older callers, tests) are resolved here from the prompt."""
    root = Path(root)
    if route.target_function and route.target_file:
        return root / route.target_file, route.target_function, route.target_exists, route.target_file
    avoid = {lit for n in route.negative_nodes for lit in n.forbidden_literals}
    target = resolve_target(prompt, root, avoid=avoid)
    rel = target.path.relative_to(root).as_posix() if target.path.is_relative_to(root) else str(target.path)
    return target.path, target.function, target.exists, rel


def target_source(path: Path, function_name: str, exists: bool) -> str:
    """Current source of the target function, or "" when it is new."""
    if not exists or not path.exists():
        return ""
    try:
        return extract_function_source(path, function_name)
    except Exception:
        return ""


def extract_function_source(file_path: Path, function_name: str) -> str:
    content = file_path.read_text(encoding="utf-8", errors="ignore")
    tree = ast.parse(content)
    lines = content.splitlines(keepends=True)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            start = node.lineno - 1
            if node.decorator_list:
                start = node.decorator_list[0].lineno - 1
            end = node.end_lineno
            return "".join(lines[start:end]).rstrip()
    raise ValueError(f"Function {function_name} not found in {file_path}")


def format_date(dt: Optional[datetime]) -> str:
    if dt is None:
        return "unknown"
    return dt.strftime("%Y-%m-%d")


def compile_leaf(
    route: RouteResult,
    graph: MemoryGraph,
    prompt: str,
    workspace_root: Union[str, Path] = "demo_vault",
) -> str:
    root = Path(workspace_root)

    # 1. Format ACTIVE DECISIONS block
    # Order: primary first, then other active_policy_ids
    active_ids_ordered: List[str] = []
    if route.primary_policy_id:
        active_ids_ordered.append(route.primary_policy_id)
    for pid in route.active_policy_ids:
        if pid not in active_ids_ordered:
            active_ids_ordered.append(pid)

    def describe(node: GraphNode, literals_label: str) -> str:
        return (
            f"- {node.id} {node.label} (in force since {format_date(node.valid_from)})\n"
            f"  {literals_label}: {', '.join(node.required_literals)}\n"
            f"  Decision: {node.description[:400].strip()}"
        )

    nodes = [n for pid in active_ids_ordered if (n := graph.node(pid))]
    governing_nodes = nodes[:1] if route.primary_policy_id else nodes
    active_decisions_text = "\n".join(describe(n, "Required literals") for n in governing_nodes)
    # Explanations see every decision in force. Code generation sees only the governing one:
    # a 7B model told about unrelated decisions (e.g. log masking) applies them anyway, and
    # their retired literals still reach it through FORBIDDEN below.
    all_decisions_text = "\n".join(describe(n, "Required literals") for n in nodes)

    # 2. Format FORBIDDEN IN PRODUCTION block
    forbidden_lines = []
    seen_forbidden = set()
    for neg_node in route.negative_nodes:
        neg_date = format_date(neg_node.superseded_at)
        for lit in neg_node.forbidden_literals:
            if lit not in seen_forbidden:
                seen_forbidden.add(lit)
                forbidden_lines.append(f"- {lit}  (from {neg_node.id}, superseded on {neg_date})")
    forbidden_text = "\n".join(forbidden_lines) if forbidden_lines else "- none"

    # 3. Handle explain_only
    if route.task_type == "explain_only":
        return (
            "Answer the user's question about this repository in five sentences or fewer,\n"
            "using the decisions below. Cite the decision ids. Do not write code.\n"
            "ACTIVE DECISIONS:\n"
            f"{all_decisions_text}\n"
            "FORBIDDEN IN PRODUCTION:\n"
            f"{forbidden_text}\n"
            "USER REQUEST:\n"
            f"{prompt}"
        )

    # 4. Handle implement_production: the function System 1 chose from the workspace's code
    target_file, function_name, exists, rel_target_str = route_target(route, root, prompt)
    current_source = target_source(target_file, function_name, exists)

    # Workspace functions the active decisions require the code to call
    governing = active_ids_ordered[:1]
    required = [lit for pid in governing if (n := graph.node(pid)) for lit in n.required_literals]
    helpers = helper_signatures(root, required, exclude=function_name)
    helpers_text = "\n".join(f"- {h}" for h in helpers) if helpers else "none"

    # Habits from earlier approvals
    if route.habits:
        habits_text = "\n".join(f"- {h.label}" for h in route.habits)
    else:
        habits_text = "none"

    if current_source:
        edit_rule = (
            f"The block replaces the function named {function_name} in {rel_target_str}.\n"
            "Keep the function name and its parameter signature intact.\n\n"
        )
        edit_block = f"file: {rel_target_str}\nfunction: {function_name}\ncurrent source:\n{current_source}\n\n"
    else:
        edit_rule = (
            f"The block is a new function named {function_name}, added to {rel_target_str}.\n"
            "Include any imports it needs inside the block, above the function.\n\n"
        )
        edit_block = f"file: {rel_target_str}\nnew function: {function_name}\n\n"

    leaf_text = (
        "You edit one private repository that stays on this machine.\n"
        "Obey ACTIVE DECISIONS and FORBIDDEN. If they conflict with older code, the decisions win.\n"
        "Reply with one fenced python block and nothing else.\n"
        f"{edit_rule}"
        "ACTIVE DECISIONS:\n"
        f"{active_decisions_text}\n\n"
        "FORBIDDEN IN PRODUCTION:\n"
        f"{forbidden_text}\n\n"
        "HABITS FROM EARLIER APPROVALS:\n"
        f"{habits_text}\n\n"
        "EDIT ONLY:\n"
        f"{edit_block}"
        "HELPERS THE DECISIONS REQUIRE, already in the repo:\n"
        f"{helpers_text}\n\n"
        "Call helpers with every parameter their signature requires, and call nothing that\n"
        "is neither listed here nor defined in your block.\n"
        "Habits come from human edits to earlier patches: when a habit sets an argument\n"
        "on a call you make, use exactly that value.\n\n"
        "USER REQUEST:\n"
        f"{prompt}"
    )
    return leaf_text
