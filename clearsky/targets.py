"""Which function a coding request should edit, chosen from the workspace's own code.

Order of evidence:
1. The prompt names a function that exists (`persist_session_token`), or a file and function.
2. Word overlap between the prompt and each function's name, file and docstring, with a bonus
   for unimplemented stubs (the usual thing someone asks to have written).
3. When the top candidates are close, openJev Verdict picks between them (or says "new function").
4. Nothing matches: a new function, named from the request, in the best-matching file.
"""

from __future__ import annotations
import ast
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from aegis.core.models import ChoiceOption, ChoiceQuery

SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".tox", "build", "dist", ".aegis", ".mypy_cache"}
MAX_FILES = 3000
MAX_VERDICT_CANDIDATES = 5
NEW_FUNCTION_ID = "__new_function__"
NEW_FILE_NAME = "new_code.py"
STOP = {
    "the", "and", "for", "with", "that", "this", "using", "use", "our", "current", "add", "implement",
    "write", "create", "make", "function", "method", "def", "code", "new", "please", "can", "you", "into",
    "from", "should", "must", "want", "need", "like", "because", "standard", "way", "just", "all",
}


@dataclass(frozen=True)
class FunctionInfo:
    path: str  # relative to the workspace root
    name: str
    signature: str
    doc: str
    stub: bool
    required: Tuple[str, ...] = ()  # parameters without defaults (self/cls excluded)


@dataclass
class Target:
    path: Path
    function: str
    exists: bool
    reason: str
    source: str = "none"  # named | overlap | verdict | new


# (path, mtime_ns, size) -> functions; only new or edited files are re-parsed
_INDEX_CACHE: Dict[Tuple[str, int, int], List[FunctionInfo]] = {}


def _words(text: str) -> List[str]:
    parts = re.findall(r"[A-Za-z][a-z0-9]*|[0-9]+", text.replace("_", " "))
    return [p.lower() for p in parts if len(p) >= 3 and p.lower() not in STOP]


def _match(a: str, b: str) -> bool:
    return a == b or (min(len(a), len(b)) >= 4 and (a.startswith(b) or b.startswith(a)))


def _is_stub(node: ast.AST) -> bool:
    body = [n for n in node.body if not (isinstance(n, ast.Expr) and isinstance(getattr(n, "value", None), ast.Constant))]
    if not body:
        return True
    if len(body) != 1:
        return False
    only = body[0]
    if isinstance(only, ast.Pass):
        return True
    if isinstance(only, ast.Expr) and isinstance(only.value, ast.Constant) and only.value.value is Ellipsis:
        return True
    if isinstance(only, ast.Raise) and only.exc is not None:
        exc = only.exc.func if isinstance(only.exc, ast.Call) else only.exc
        return isinstance(exc, ast.Name) and exc.id == "NotImplementedError"
    return False


def _required_params(node) -> Tuple[str, ...]:
    a = node.args
    positional = a.posonlyargs + a.args
    no_default = positional[: len(positional) - len(a.defaults)]
    names = [p.arg for p in no_default if p.arg not in ("self", "cls")]
    names += [k.arg for k, d in zip(a.kwonlyargs, a.kw_defaults) if d is None]
    return tuple(names)


def _is_test_path(rel: str) -> bool:
    parts = rel.split("/")
    return any(p in ("tests", "test", "testing") for p in parts[:-1]) or parts[-1].startswith("test_") or parts[-1] == "conftest.py"


def python_files(root: Path) -> Iterable[Path]:
    count = 0
    for path in sorted(root.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts[:-1]):
            continue
        count += 1
        if count > MAX_FILES:
            return
        yield path


def _functions_in(path: Path, rel: str) -> List[FunctionInfo]:
    st = path.stat()
    key = (str(path), st.st_mtime_ns, st.st_size)
    if key in _INDEX_CACHE:
        return _INDEX_CACHE[key]
    found: List[FunctionInfo] = []
    try:
        source = path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source)
        lines = source.splitlines()
        # Module-level functions and methods one class deep
        nodes = list(tree.body) + [n for c in tree.body if isinstance(c, ast.ClassDef) for n in c.body]
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = (ast.get_docstring(node) or "").strip().split("\n")[0][:160]
                signature = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else f"def {node.name}(...)"
                found.append(FunctionInfo(rel, node.name, signature, doc, _is_stub(node), _required_params(node)))
    except (SyntaxError, ValueError, OSError):
        pass
    _INDEX_CACHE[key] = found
    return found


# root -> (built at, index). Walking a large repo costs ~50 ms even with every file cached,
# so the index is reused for a few seconds; patches ClearSky applies call forget_index().
INDEX_TTL_S = 5.0
_ROOT_INDEX: Dict[str, Tuple[float, List[FunctionInfo]]] = {}


def forget_index(root) -> None:
    _ROOT_INDEX.pop(str(Path(root).resolve()), None)


def function_index(root: Path) -> List[FunctionInfo]:
    """Every module-level function and method under root, skipping tests and tooling folders."""
    root = Path(root)
    if not root.is_dir():
        return []
    key = str(root.resolve())
    hit = _ROOT_INDEX.get(key)
    if hit and time.monotonic() - hit[0] < INDEX_TTL_S:
        return hit[1]
    index: List[FunctionInfo] = []
    for path in python_files(root):
        rel = path.relative_to(root).as_posix()
        if _is_test_path(rel):
            continue
        index.extend(_functions_in(path, rel))
    _ROOT_INDEX[key] = (time.monotonic(), index)
    return index


def _score(prompt_words: Sequence[str], fn: FunctionInfo) -> float:
    name_words = _words(fn.name)
    file_words = _words(Path(fn.path).stem)
    doc_words = _words(fn.doc)
    score = 0.0
    for w in set(prompt_words):
        if any(_match(w, n) for n in name_words):
            score += 2.0
        elif any(_match(w, f) for f in file_words):
            score += 0.75
        elif any(_match(w, d) for d in doc_words):
            score += 0.5
    if score and fn.stub:
        score += 1.0
    return score


def new_function_name(prompt: str) -> str:
    """snake_case name from "add a X function", else from the request's leading words."""
    m = re.search(r"\b(?:add|create|write|implement|make|build)\s+(?:a|an|the)?\s*(?:new\s+)?(.+?)\s+(?:function|method|helper)\b",
                  prompt, re.IGNORECASE)
    words = _words(m.group(1)) if m else []
    if not words:
        m = re.search(r"\b(?:function|method|helper)\s+(?:that|to|which)\s+(.+)", prompt, re.IGNORECASE)
        words = _words(m.group(1)) if m else _words(prompt)
    return "_".join(words[:4]) or "new_function"


def _named(prompt: str, index: List[FunctionInfo], avoid: set) -> Optional[FunctionInfo]:
    # Only identifier-shaped words count: snake_case, camelCase, `quoted` or called(); plain
    # English ("encrypt", "query") names too many library functions to mean one of them
    identifiers = {
        w for w in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", prompt)
        if "_" in w.strip("_") or re.search(r"[a-z][A-Z]", w) or f"`{w}`" in prompt or (f"{w}(" in prompt and f".{w}(" not in prompt)
    }
    hits = [f for f in index if f.name in identifiers and f.name not in avoid]
    if not hits:
        return None
    # Prefer the function whose file the prompt also names, then stubs, then the shortest path
    def rank(f: FunctionInfo):
        return (Path(f.path).stem not in prompt and f.path not in prompt, not f.stub, len(f.path), f.path)
    return sorted(hits, key=rank)[0]


def _ask_verdict(engine, prompt: str, root: Path, candidates: List[FunctionInfo]) -> Optional[str]:
    options = [
        ChoiceOption(id=f"{f.path}::{f.name}", description=f"Edit {f.name} in {f.path}. {f.doc}".strip())
        for f in candidates
    ]
    options.append(ChoiceOption(id=NEW_FUNCTION_ID, description="Write a new function; none of the existing ones fit."))
    query = ChoiceQuery(
        id="edit_target",
        question="Which function should this coding request change?",
        options=options,
        allow_abstention=True,
    )
    context = f"Repository: {root.resolve().name}.\nThe user said: {prompt}"
    res = engine.evaluate_choice(context=context, query=query)
    ids = {o.id for o in options}
    real = {k: v for k, v in res.probabilities.items() if k in ids}
    return max(real, key=real.get) if real else None


def resolve_target(
    prompt: str,
    workspace_root,
    engine=None,
    avoid: Iterable[str] = (),
) -> Target:
    """Pick the function to edit. `avoid` holds names that must not be edited (forbidden literals)."""
    root = Path(workspace_root)
    avoid_set = set(avoid)
    index = [f for f in function_index(root) if f.name not in avoid_set]

    named = _named(prompt, index, avoid_set)
    if named:
        return Target(root / named.path, named.name, True, f"the request names {named.name}", "named")

    # "Add a revoke_session_token function": a snake_case name the code doesn't have yet is new
    asked = new_function_name(prompt)
    if "_" in asked and re.search(rf"\b{re.escape(asked)}\b", prompt):
        scored_files = sorted(((s, f) for f in index if (s := _score(_words(prompt), f)) > 0), key=lambda x: (-x[0], x[1].path))
        return _new_target(prompt, root, scored_files, f"the request names a new function, {asked}", "new", avoid_set)

    words = _words(prompt)
    scored = sorted(((s, f) for f in index if (s := _score(words, f)) > 0), key=lambda x: (-x[0], x[1].path))
    if scored:
        best_score, best = scored[0]
        close = [f for s, f in scored if s >= best_score - 1.0][:MAX_VERDICT_CANDIDATES]
        if len(close) > 1 and engine is not None:
            try:
                pick = _ask_verdict(engine, prompt, root, close)
            except Exception:
                pick = None
            if pick == NEW_FUNCTION_ID:
                return _new_target(prompt, root, scored, "Verdict judged that no existing function fits", "verdict", avoid_set)
            for f in close:
                if pick == f"{f.path}::{f.name}":
                    return Target(root / f.path, f.name, True, f"Verdict chose it over {len(close) - 1} similar functions", "verdict")
        name_hits = sum(1 for n in set(_words(best.name)) if any(_match(w, n) for w in words))
        if name_hits >= 2 or (name_hits and name_hits * 2 >= len(set(_words(best.name)))):
            return Target(root / best.path, best.name, True, f"closest match to the request ({best_score:g} points)", "overlap")

    return _new_target(prompt, root, scored, "no existing function matches the request", "new", avoid_set)


def _new_target(prompt: str, root: Path, scored, reason: str, source: str, avoid: set) -> Target:
    name = new_function_name(prompt)
    if name in avoid:
        name = f"{name}_new"
    if scored:
        path = root / scored[0][1].path
    else:
        path = root / NEW_FILE_NAME
    existing = {f.name for f in _functions_in(path, "")} if path.exists() else set()
    return Target(path, name, name in existing, reason, source)


def helper_signatures(root: Path, symbols: Iterable[str], exclude: str = "") -> List[str]:
    """`path: def ...` lines (plus first docstring line) for workspace functions the decisions require."""
    wanted = {s for s in symbols if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", s or "")}
    wanted.discard(exclude)
    if not wanted:
        return []
    lines = []
    for f in function_index(Path(root)):
        if f.name in wanted:
            wanted.discard(f.name)
            line = f"{f.path}: {f.signature}" + (f"  # {f.doc}" if f.doc else "")
            if f.required:
                line += f"\n  every call must pass: {', '.join(f.required)}"
            lines.append(line)
    return lines
