"""Human-in-the-loop feedback processor, habit extractor, and safe disk writer.
"""

from __future__ import annotations
import ast
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from aegis.core.models import GraphNode
from aegis.system1.graph import MemoryGraph


def _constant_source(node: ast.AST) -> Optional[str]:
    """Source text for literal values (numbers, strings, bools, None, -n); None otherwise."""
    if isinstance(node, ast.Constant):
        return repr(node.value) if isinstance(node.value, str) else str(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant):
        return f"-{node.operand.value}"
    return None


def _call_name(func: ast.AST) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return "call"


def _literal_kwargs(source: str) -> Optional[List[Tuple[str, str, str]]]:
    """(callee, keyword, value) for every call keyword set to a literal, in source order."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            callee = _call_name(node.func)
            for kw in node.keywords:
                value = _constant_source(kw.value) if kw.arg else None
                if value is not None:
                    found.append(((kw.value.lineno, kw.value.col_offset), callee, kw.arg, value))
    return [item[1:] for item in sorted(found)]


def _regex_kwargs(source: str) -> List[Tuple[str, str, str]]:
    """Fallback when code does not parse: keyword=literal pairs on each line."""
    pattern = re.compile(r"""\b([A-Za-z_]\w*)\s*=\s*(-?[0-9][0-9.]*|"[^"]*"|'[^']*'|True|False|None)""")
    return [("call", m.group(1), m.group(2)) for line in source.splitlines() for m in pattern.finditer(line)]


def extract_habits(model_output: str, approved_output: str) -> List[Dict[str, Any]]:
    """Keyword arguments the reviewer set to a different literal than the model did.

    Any call in the approved code whose literal keyword value was added or
    changed relative to the model's patch becomes a habit, scoped to the
    callee: editing aegis_seal(..., retries=3) to retries=1 yields
    "Calls to aegis_seal must set retries=1."
    """
    before = _literal_kwargs(model_output)
    after = _literal_kwargs(approved_output)
    if before is None or after is None:
        before, after = _regex_kwargs(model_output), _regex_kwargs(approved_output)

    before_values = {(callee, kw): value for callee, kw, value in before}
    habits: List[Dict[str, Any]] = []
    seen = set()
    for callee, kw, value in after:
        if (callee, kw) in seen or before_values.get((callee, kw)) == value:
            continue
        seen.add((callee, kw))
        target = f"Calls to {callee}" if callee != "call" else "Production calls"
        habits.append({
            "key": f"{callee}:{kw}",
            "callee": callee,
            "argument": kw,
            "value": value,
            "previous_value": before_values.get((callee, kw)),
            "label": f"{target} must set {kw}={value}.",
            "source": "approval_diff",
        })
    return habits


def replace_function_source(
    file_path: Path,
    function_name: str,
    new_code: str,
) -> None:
    """Replaces only the target function definition in file_path with new_code."""
    content = file_path.read_text(encoding="utf-8")
    tree = ast.parse(content)
    lines = content.splitlines(keepends=True)

    target_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            target_node = node
            break

    if target_node is None:
        raise ValueError(f"Function {function_name} not found in {file_path}")

    start = target_node.lineno - 1
    end = target_node.end_lineno

    # Ensure clean newline
    cleaned_new = new_code.strip() + "\n"
    new_lines = lines[:start] + [cleaned_new] + lines[end:]
    file_path.write_text("".join(new_lines), encoding="utf-8")
