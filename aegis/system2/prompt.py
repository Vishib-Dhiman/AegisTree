"""Baseline Prompt Compiler, Code Extractor, and Diff Utilities for System 2.
"""

from __future__ import annotations
import difflib
import re
from pathlib import Path
from typing import Optional, Union

from aegis.system1.leaf import select_function_name


def compile_baseline(
    prompt: str,
    workspace_root: Union[str, Path] = "demo_vault",
    function_name: Optional[str] = None,
) -> str:
    root = Path(workspace_root)
    fn_name = function_name or select_function_name(prompt)

    # Gather every file under workspace_root, path-sorted
    file_blocks = []
    if root.exists():
        all_files = [p for p in root.rglob("*") if p.is_file() and not p.name.startswith(".")]
        # Sort by relative path string
        all_files.sort(key=lambda p: str(p.relative_to(root)))
        for p in all_files:
            rel_path = str(p.relative_to(root))
            content = p.read_text(encoding="utf-8", errors="ignore")
            file_blocks.append(f"----- {rel_path} -----\n{content}")

    repo_files_text = "\n\n".join(file_blocks)

    baseline_text = (
        "You are a local coding assistant. Implement the user request using this repository.\n"
        "Prefer the patterns already present in the code.\n"
        "Reply with one fenced python block and nothing else.\n"
        f"The block replaces the function named {fn_name} in vault/store.py.\n\n"
        "REPOSITORY FILES:\n"
        f"{repo_files_text}\n\n"
        "USER REQUEST:\n"
        f"{prompt}"
    )
    return baseline_text


def extract_code(text: str) -> str:
    """Extract code from the model output. Takes first fenced block or raw text."""
    # Look for ```python or ``` block
    fence_pattern = re.compile(r"```(?:python)?\s*\n(.*?)\n```", re.DOTALL | re.IGNORECASE)
    match = fence_pattern.search(text)
    if match:
        return match.group(1).strip()
    # Strip any dangling backticks
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:python)?\s*", "", cleaned)
    if cleaned.endswith("```"):
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def is_code_parseable(code: str, function_name: str) -> bool:
    """The result must contain 'def {function_name}'."""
    pattern = rf"def\s+{re.escape(function_name)}\b"
    return bool(re.search(pattern, code))


def compute_unified_diff(old_code: str, new_code: str, filename: str = "vault/store.py") -> str:
    """Computes unified line diff between old and new function implementations."""
    old_lines = old_code.splitlines(keepends=True)
    new_lines = new_code.splitlines(keepends=True)
    # Ensure newline terminated for clean diffs
    if old_lines and not old_lines[-1].endswith("\n"):
        old_lines[-1] += "\n"
    if new_lines and not new_lines[-1].endswith("\n"):
        new_lines[-1] += "\n"
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
    )
    return "".join(diff)
