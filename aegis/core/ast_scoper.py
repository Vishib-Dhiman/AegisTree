"""
AST Syntactic Scope Extractor for AegisTree.
Deterministically classifies code scopes (test mock vs. comment vs. production execution)
to prevent false-positive architectural compliance violations.
"""

from __future__ import annotations
import ast
import re
from enum import Enum
from pathlib import Path
from typing import List, Dict, Any, Optional
from pydantic import BaseModel


class ScopeType(str, Enum):
    PRODUCTION_EXECUTION = "production_execution"
    TEST_FIXTURE = "test_fixture"
    DOCSTRING_COMMENT = "docstring_comment"
    DEAD_CODE = "dead_code"


class ScopedSnippet(BaseModel):
    filepath: str
    line_number: int
    scope: ScopeType
    content: str
    is_safe_deprecation_test: bool = False
    metadata: Dict[str, Any] = {}


class ASTScoper:
    """Lightweight deterministic syntax and scope classifier."""

    TEST_PATH_PATTERNS = [
        re.compile(r"(^|[/\\])tests?([/\\].*)?$", re.IGNORECASE),
        re.compile(r"_test\.py$", re.IGNORECASE),
        re.compile(r"test_.*\.py$", re.IGNORECASE),
        re.compile(r"(^|[/\\])mocks?([/\\].*)?$", re.IGNORECASE),
        re.compile(r"(^|[/\\])fixtures?([/\\].*)?$", re.IGNORECASE),
    ]

    DEPRECATION_ASSERTION_PATTERNS = [
        re.compile(r"pytest\.deprecated_call", re.IGNORECASE),
        re.compile(r"pytest\.warns\(.*DeprecationWarning.*\)", re.IGNORECASE),
        re.compile(r"assertWarns\(.*DeprecationWarning.*\)", re.IGNORECASE),
        re.compile(r"with\s+warnings\.catch_warnings", re.IGNORECASE),
    ]

    @classmethod
    def is_test_file(cls, filepath: str) -> bool:
        normalized = filepath.replace("\\", "/")
        return any(pattern.search(normalized) for pattern in cls.TEST_PATH_PATTERNS)

    @classmethod
    def is_deprecation_assertion(cls, snippet: str) -> bool:
        return any(pattern.search(snippet) for pattern in cls.DEPRECATION_ASSERTION_PATTERNS)

    @classmethod
    def is_pure_comment_or_docstring(cls, snippet: str) -> bool:
        lines = [line.strip() for line in snippet.strip().splitlines() if line.strip()]
        if not lines:
            return True
        # Check if all lines start with #
        if all(line.startswith("#") or line.startswith("//") for line in lines):
            return True
        # Check if wrapped in triple quotes
        joined = "\n".join(lines)
        if (joined.startswith('"""') and joined.endswith('"""')) or (joined.startswith("'''") and joined.endswith("'''")):
            return True
        return False

    @classmethod
    def classify_snippet(cls, filepath: str, snippet: str, line_number: int = 1) -> ScopedSnippet:
        """Classifies the syntactic scope of a code snippet within a given file."""
        if cls.is_pure_comment_or_docstring(snippet):
            return ScopedSnippet(
                filepath=filepath,
                line_number=line_number,
                scope=ScopeType.DOCSTRING_COMMENT,
                content=snippet,
                is_safe_deprecation_test=False,
                metadata={"reason": "Pure comment or docstring block"}
            )

        if cls.is_test_file(filepath):
            is_dep_test = cls.is_deprecation_assertion(snippet)
            return ScopedSnippet(
                filepath=filepath,
                line_number=line_number,
                scope=ScopeType.TEST_FIXTURE,
                content=snippet,
                is_safe_deprecation_test=is_dep_test,
                metadata={
                    "reason": "Located inside test suite or mock directory",
                    "is_testing_deprecation": is_dep_test
                }
            )

        # Production execution scope
        return ScopedSnippet(
            filepath=filepath,
            line_number=line_number,
            scope=ScopeType.PRODUCTION_EXECUTION,
            content=snippet,
            is_safe_deprecation_test=False,
            metadata={"reason": "Executable production business logic"}
        )

    @classmethod
    def parse_python_imports(cls, code: str) -> List[str]:
        """Extracts top-level imported module names using Python's native AST."""
        imports = []
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.append(node.module)
        except Exception:
            # Fallback to regex if syntax error
            for match in re.finditer(r"^\s*(?:import|from)\s+([a-zA-Z0-9_\.]+)", code, re.MULTILINE):
                imports.append(match.group(1))
        return list(set(imports))

    @classmethod
    def scope_file(cls, path: Path | str) -> ScopedSnippet:
        """Reads file at path and classifies its scope."""
        p = Path(path)
        content = p.read_text(encoding="utf-8", errors="ignore") if p.exists() else ""
        return cls.classify_snippet(str(path), content, line_number=1)

