"""Leaf Context Compiler for AegisTree.
Builds the minimal, strictly bounded prompt for System 2 containing active decisions,
closure bans, habits, and only the target function to edit.
"""

from __future__ import annotations
import ast
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Union

from aegis.core.models import GraphNode
from aegis.system1.graph import MemoryGraph
from aegis.system1.router import RouteResult


def estimate_tokens(text: str) -> int:
    """Estimator: max(1, (len(text) + 3) // 4) with label 'chars/4 estimate'."""
    return max(1, (len(text) + 3) // 4)


def select_target(prompt: str, root: Path) -> tuple[Path, str]:
    p_low = prompt.lower()
    if "oaep" in p_low or "rsa" in p_low or "encrypt" in p_low:
        return root / "vault" / "crypto.py", "encrypt_rsa_payload"
    elif "pydantic" in p_low or "serialize" in p_low or "model_dump" in p_low:
        return root / "vault" / "schemas.py", "serialize_vault_payload"
    elif "sqlalchemy" in p_low or "database" in p_low or "audit" in p_low:
        return root / "vault" / "db.py", "query_audit_trail"
    elif "rotate" in p_low:
        return root / "vault" / "store.py", "rotate_session_token"
    else:
        return root / "vault" / "store.py", "persist_session_token"


def select_function_name(prompt: str) -> str:
    p_low = prompt.lower()
    if "oaep" in p_low or "rsa" in p_low or "encrypt" in p_low:
        return "encrypt_rsa_payload"
    elif "pydantic" in p_low or "serialize" in p_low or "model_dump" in p_low:
        return "serialize_vault_payload"
    elif "sqlalchemy" in p_low or "database" in p_low or "audit" in p_low:
        return "query_audit_trail"
    elif "rotate" in p_low:
        return "rotate_session_token"
    return "persist_session_token"


def extract_function_source(file_path: Path, function_name: str) -> str:
    content = file_path.read_text(encoding="utf-8", errors="ignore")
    tree = ast.parse(content)
    lines = content.splitlines(keepends=True)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            start = node.lineno - 1
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

    active_decisions_lines = []
    for pid in active_ids_ordered:
        node = graph.node(pid)
        if node:
            date_str = format_date(node.valid_from)
            req_str = ", ".join(node.required_literals)
            desc_str = node.description[:400].strip()
            active_decisions_lines.append(
                f"- {node.id} {node.label} (in force since {date_str})\n"
                f"  Required literals: {req_str}\n"
                f"  Decision: {desc_str}"
            )
    active_decisions_text = "\n".join(active_decisions_lines)

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
            "Explain, in five sentences or fewer, how session tokens must be persisted.\n"
            "Cite the active decision ids. Do not write code.\n"
            "ACTIVE DECISIONS:\n"
            f"{active_decisions_text}\n"
            "FORBIDDEN IN PRODUCTION:\n"
            f"{forbidden_text}\n"
            "USER REQUEST:\n"
            f"{prompt}"
        )

    # 4. Handle implement_production
    target_file, function_name = select_target(prompt, root)
    if not target_file.exists():
        target_file = root / "vault" / "store.py"
        function_name = "persist_session_token"
    current_source = extract_function_source(target_file, function_name)
    rel_target_str = str(target_file.relative_to(root)) if target_file.is_relative_to(root) else str(target_file)

    seal_py = root / "vault" / "seal.py"
    seal_source = seal_py.read_text(encoding="utf-8", errors="ignore").strip() if seal_py.exists() else ""

    # Habits from earlier approvals
    if route.habits:
        habits_text = "\n".join(f"- {h.label}" for h in route.habits)
    else:
        habits_text = "none"

    leaf_text = (
        "You edit one private repository that stays on this machine.\n"
        "Obey ACTIVE DECISIONS and FORBIDDEN. If they conflict with older code, the decisions win.\n"
        "Reply with one fenced python block and nothing else.\n"
        f"The block replaces the body of the function named {function_name} in {rel_target_str}.\n"
        "Keep the function name and its parameter signature intact.\n\n"
        "ACTIVE DECISIONS:\n"
        f"{active_decisions_text}\n\n"
        "FORBIDDEN IN PRODUCTION:\n"
        f"{forbidden_text}\n\n"
        "HABITS FROM EARLIER APPROVALS:\n"
        f"{habits_text}\n\n"
        "EDIT ONLY:\n"
        f"file: {rel_target_str}\n"
        f"function: {function_name}\n"
        "current source:\n"
        f"{current_source}\n\n"
        "ALLOWED HELPER, already in the repo:\n"
        f"{seal_source}\n\n"
        "If a habit specifies retries, use that value; otherwise retries=3.\n"
        "If a habit specifies timeout_s, use that value.\n\n"
        "USER REQUEST:\n"
        f"{prompt}"
    )
    return leaf_text
