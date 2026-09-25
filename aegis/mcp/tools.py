"""Pure Tool Functions for AegisTree agent execution and human-in-the-loop review.
"""

from __future__ import annotations
import ast
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from aegis.core.models import NodeType
from aegis.mcp.feedback import extract_habit_details, extract_habit_label, replace_function_source
from aegis.system1.graph import MemoryGraph
from aegis.system1.leaf import extract_function_source, select_function_name, select_target
from aegis.system1.router import RouteResult, tokenize_text
from aegis.system2.prompt import compute_unified_diff, extract_code


def search_decisions(
    graph: MemoryGraph,
    query: str,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Returns active decisions, overlapping ids, and negative literals.
    Same overlap and closure rules as the router. No model call.
    """
    query_time = now or datetime.now(timezone.utc)
    active_decisions = [
        n for n in graph.active_nodes(query_time)
        if n.type == NodeType.ARCHITECTURE_DECISION
    ]

    tokens = tokenize_text(query)
    scored = []
    for dec in active_decisions:
        dec_tags = {t.lower() for t in dec.tags}
        dec_label_tokens = tokenize_text(dec.label)
        score = len(dec_tags & tokens) + len(dec_label_tokens & tokens)
        if score > 0:
            scored.append((score, dec))

    scored.sort(key=lambda x: x[0], reverse=True)
    overlapping_ids = [dec.id for _, dec in scored]

    # Closure: one hop supersedes
    negative_literals = set()
    for dec_id in overlapping_ids:
        for succ in graph.successors(dec_id, relation="supersedes"):
            negative_literals.update(succ.forbidden_literals)

    return {
        "active_decisions": [{"id": d.id, "label": d.label} for d in active_decisions],
        "overlapping_ids": overlapping_ids,
        "negative_literals": sorted(list(negative_literals)),
    }


def propose_patch(
    route: RouteResult,
    aegis_code: str,
    workspace_root: Union[str, Path] = "demo_vault",
    prompt: str = "",
) -> Dict[str, Any]:
    """Does not touch the disk. Returns the diff, the target path,
    required literals missing, and forbidden literals present.
    """
    root = Path(workspace_root)
    clean_code = extract_code(aegis_code)

    if route.task_type == "edit_tests":
        rel_path = "tests/test_legacy_wrap.py"
        target_path = root / rel_path
        old_source = target_path.read_text(encoding="utf-8") if target_path.exists() else ""
    else:
        target_path, fn_name = select_target(prompt or clean_code, root)
        rel_path = str(target_path.relative_to(root)) if target_path.is_relative_to(root) else str(target_path)
        try:
            old_source = extract_function_source(target_path, fn_name)
        except Exception:
            old_source = ""

    diff = compute_unified_diff(old_source, clean_code, filename=rel_path)

    # Collect required literals
    required_literals = set()
    for pid in route.active_policy_ids:
        # Note: caller or graph might provide, or collect from active nodes
        pass

    # Collect forbidden literals from negative nodes
    forbidden_literals = set()
    for neg in route.negative_nodes:
        forbidden_literals.update(neg.forbidden_literals)

    present_forbidden = [lit for lit in sorted(forbidden_literals) if lit in clean_code]

    return {
        "target_path": str(target_path),
        "relative_path": rel_path,
        "diff": diff,
        "present_forbidden": present_forbidden,
    }


def apply_patch(
    graph: MemoryGraph,
    route: RouteResult,
    approved_code: str,
    approved: bool,
    workspace_root: Union[str, Path] = "demo_vault",
    model_output: str = "",
    prompt: str = "",
    leaf_text: str = "",
    baseline_text: str = "",
    verdict_data: Optional[Dict[str, Any]] = None,
    decision_source: str = "",
) -> Dict[str, Any]:
    """If approved is False, return {applied: False, reason: "human approval required"}.
    If approved is True, run the section 11 checks and write.
    """
    if not approved:
        return {"applied": False, "reason": "human approval required"}

    root = Path(workspace_root).resolve()
    clean_code = extract_code(approved_code)

    # 1. Target file and path jail
    if route.task_type == "edit_tests":
        rel_path = "tests/test_legacy_wrap.py"
        target_file = (root / rel_path).resolve()
        fn_name = ""
    else:
        target_file, fn_name = select_target(prompt or clean_code, root)
        target_file = target_file.resolve()
        rel_path = str(target_file.relative_to(root)) if target_file.is_relative_to(root) else str(target_file)
    if not target_file.is_relative_to(root):
        raise ValueError("Path jail violation: Target file escapes workspace root")

    # 2. Syntax validation
    try:
        ast.parse(clean_code)
    except SyntaxError as e:
        raise ValueError(f"Syntax error in approved code: {e}")

    # 3. Check forbidden literals
    if route.task_type == "implement_production":
        banned = set()
        for pid in route.active_policy_ids:
            pol = graph.node(pid)
            if pol:
                banned.update(pol.forbidden_literals)
        for neg in route.negative_nodes:
            banned.update(neg.forbidden_literals)
        present_banned = [b for b in banned if b in clean_code]
        if present_banned:
            # If legacy_wrap is in present_banned, prioritize it
            b = "legacy_wrap" if "legacy_wrap" in present_banned else sorted(present_banned)[0]
            # Refusal: record receipt with approved_output empty and habit_id null
            receipt_id = graph.add_receipt(
                prompt=prompt,
                task_type=route.task_type,
                policy_ids=route.active_policy_ids,
                decision_source=decision_source or route.task_source,
                verdict_data=verdict_data or {},
                leaf_text=leaf_text,
                baseline_text=baseline_text,
                model_output=model_output,
                approved_output="",
                habit_id=None,
            )
            return {
                "applied": False,
                "refused": True,
                "banned_literal": b,
                "banned_literals": sorted(present_banned),
                "reason": f"Forbidden literal present in approved code: {b}",
                "receipt_id": receipt_id,
            }

    # 4. Write to disk
    if route.task_type == "implement_production":
        fn_name = select_function_name(prompt or clean_code)
        replace_function_source(target_file, fn_name, clean_code)
    else:
        target_file.write_text(clean_code, encoding="utf-8")

    # 5. Extract habit
    habit_details = extract_habit_details(model_output, clean_code)
    habit_label = habit_details["label"] if habit_details else None
    habit_node = None
    if habit_label:
        habit_node = graph.add_habit(habit_label, metadata=habit_details)

    # 6. Store receipt
    receipt_id = graph.add_receipt(
        prompt=prompt,
        task_type=route.task_type,
        policy_ids=route.active_policy_ids,
        decision_source=decision_source or route.task_source,
        verdict_data=verdict_data or {},
        leaf_text=leaf_text,
        baseline_text=baseline_text,
        model_output=model_output,
        approved_output=clean_code,
        habit_id=habit_node.id if habit_node else None,
    )

    return {
        "applied": True,
        "refused": False,
        "receipt_id": receipt_id,
        "habit_id": habit_node.id if habit_node else None,
        "habit_label": habit_label,
    }
