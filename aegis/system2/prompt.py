"""Baseline Prompt Compiler, Code Extractor, and Diff Utilities for System 2.
"""

from __future__ import annotations
import difflib
import re
from pathlib import Path
from typing import Optional, Union

SKIP_BASELINE_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".aegis"}
# Source and docs only: test vectors, images and lockfiles aren't something you'd paste to a model
BASELINE_SUFFIXES = {".py", ".pyi", ".md", ".rst", ".txt", ".toml", ".cfg", ".ini", ".yaml", ".yml"}
BASELINE_MAX_FILE_BYTES = 256_000
# What an ungoverned run can actually send a small local model (qwen2.5-coder:7b: 32k tokens)
BASELINE_RUN_CHARS = 60_000


def _baseline_files(root: Path, target_rel: str) -> list[Path]:
    """Every file, nearest the target first: the target file, its folder, then the rest by path."""
    files = [
        p for p in root.rglob("*")
        if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in BASELINE_SUFFIXES
        and p.stat().st_size <= BASELINE_MAX_FILE_BYTES
        and not any(part in SKIP_BASELINE_DIRS for part in p.relative_to(root).parts[:-1])
    ]
    target_dir = str(Path(target_rel).parent)

    def rank(p: Path):
        rel = p.relative_to(root).as_posix()
        return (rel != target_rel, str(Path(rel).parent) != target_dir, rel)
    return sorted(files, key=rank)


def compile_baseline(
    prompt: str,
    workspace_root: Union[str, Path] = "demo_vault",
    function_name: Optional[str] = None,
    target_file: Optional[str] = None,
    max_chars: Optional[int] = None,
) -> str:
    """The ungoverned prompt: repository files and the request, with no decision graph.

    Without max_chars it holds the whole repository (what "send the model everything" costs).
    With max_chars it holds the files nearest the target that fit, which is what an
    ungoverned run can actually send a local model.
    """
    root = Path(workspace_root)
    fn_name = function_name or "the requested function"
    target_rel = target_file or "the most relevant file"

    file_blocks = []
    used = 0
    skipped = 0
    if root.exists():
        for p in _baseline_files(root, target_rel):
            rel_path = p.relative_to(root).as_posix()
            content = p.read_text(encoding="utf-8", errors="ignore")
            block = f"----- {rel_path} -----\n{content}"
            if max_chars is not None and used + len(block) > max_chars:
                skipped += 1
                continue
            used += len(block)
            file_blocks.append(block)

    repo_files_text = "\n\n".join(file_blocks)
    if skipped:
        repo_files_text += f"\n\n({skipped} more files did not fit in the model's context)"

    baseline_text = (
        "You are a local coding assistant. Implement the user request using this repository.\n"
        "Prefer the patterns already present in the code.\n"
        "Reply with one fenced python block and nothing else.\n"
        f"The block is the complete function named {fn_name} in {target_rel}.\n\n"
        "REPOSITORY FILES:\n"
        f"{repo_files_text}\n\n"
        "USER REQUEST:\n"
        f"{prompt}"
    )
    return baseline_text


FREE_SYSTEM_PROMPT = (
    "You are a coding assistant running entirely on this machine. "
    "No repository is attached and no architecture decisions apply. "
    "This is an ongoing conversation: resolve follow-ups such as 'now in C++' or "
    "'make it faster' against the earlier turns. "
    "Answer directly and put any code in fenced blocks."
)

# Keep the most recent turns, within a budget that fits small local models
MAX_HISTORY_TURNS = 12
MAX_HISTORY_CHARS = 12000


def build_free_messages(
    prompt: str,
    history: Optional[list] = None,
    web_context: Optional[str] = None,
    extra_system: Optional[str] = None,
) -> list[dict]:
    """Chat messages for No-workspace mode: system prompt, recent history, new request.

    extra_system, when given, is appended to the system prompt (computer access).

    web_context, when given, is a second system message placed just before the
    request (web search results for this turn only).

    history is a list of {"role": "user"|"assistant", "content": str}, oldest first.
    Turns with other roles or empty content are dropped; the newest turns are kept.
    """
    turns = [
        {"role": t["role"], "content": str(t["content"])}
        for t in (history or [])
        if isinstance(t, dict) and t.get("role") in ("user", "assistant") and str(t.get("content", "")).strip()
    ][-MAX_HISTORY_TURNS:]

    kept: list[dict] = []
    used = 0
    for turn in reversed(turns):
        used += len(turn["content"])
        if used > MAX_HISTORY_CHARS:
            break
        kept.append(turn)
    kept.reverse()
    # A conversation must not open with an assistant turn
    while kept and kept[0]["role"] == "assistant":
        kept.pop(0)

    web = [{"role": "system", "content": web_context}] if web_context else []
    system = FREE_SYSTEM_PROMPT + (f"\n\n{extra_system}" if extra_system else "")
    return [{"role": "system", "content": system}, *kept, *web, {"role": "user", "content": prompt}]


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
