"""Human-in-the-loop feedback processor, habit extractor, and safe disk writer.
"""

from __future__ import annotations
import ast
import difflib
import re
from pathlib import Path
from typing import Any, Dict, Optional, Union

from aegis.core.models import GraphNode
from aegis.system1.graph import MemoryGraph
from aegis.system1.leaf import select_function_name


def extract_habit_details(model_output: str, approved_output: str) -> Optional[Dict[str, Any]]:
    r"""Computes line diff between model output and approved output.
    Rules evaluated in order, first match wins:
    1. Added/changed line matches retries\s*=\s*(\d+) -> key=retries, value=n
    2. Else matches timeout_s\s*=\s*([0-9.]+) -> key=timeout_s, value=n
    3. Else matches key_id\s*=\s*"([^"]+)" -> key=key_id, value="val"
    4. Else None.
    """
    diff = list(difflib.ndiff(model_output.splitlines(), approved_output.splitlines()))
    added_lines = [line[2:] for line in diff if line.startswith("+ ")]
    if not added_lines:
        added_lines = approved_output.splitlines()

    for line in added_lines:
        m = re.search(r"retries\s*=\s*(\d+)", line)
        if m:
            val = m.group(1)
            return {
                "key": "retries",
                "value": val,
                "label": f"Production vault calls must set retries={val}.",
                "source": "approval_diff",
            }

    for line in added_lines:
        m = re.search(r"timeout_s\s*=\s*([0-9.]+)", line)
        if m:
            val = m.group(1)
            return {
                "key": "timeout_s",
                "value": val,
                "label": f"Production vault calls must set timeout_s={val}.",
                "source": "approval_diff",
            }

    for line in added_lines:
        m = re.search(r'key_id\s*=\s*"([^"]+)"', line)
        if m:
            val = m.group(1)
            return {
                "key": "key_id",
                "value": val,
                "label": f'Production vault calls must set key_id="{val}".',
                "source": "approval_diff",
            }

    return None


def extract_habit_label(model_output: str, approved_output: str) -> Optional[str]:
    details = extract_habit_details(model_output, approved_output)
    return details["label"] if details else None


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
