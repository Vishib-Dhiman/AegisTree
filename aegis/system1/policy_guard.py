"""Forbidden-pattern checks shared by the router (prompt side) and patch tools (code side).

Two layers:
1. Normalised literal matching. `legacy_wrap`, `LegacyWrap`, `legacy-wrap`,
   `legacy wrap` and `legacywrap` all reduce to the same token sequence.
2. A Verdict revival check for paraphrases that never name the literal
   ("the old wrap cipher"): System 1 is asked whether the request follows the
   active decision or asks for the superseded one.
"""

from __future__ import annotations
import re
from pathlib import Path
from typing import Iterable, List, Optional, Tuple, Union

from aegis.core.models import ChoiceOption, ChoiceQuery, GraphNode
from aegis.system1.engine import DecisionEngine

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def literal_tokens(text: str) -> List[str]:
    """Lowercase alphanumeric tokens, splitting camelCase and any separator."""
    return re.findall(r"[a-z0-9]+", _CAMEL_BOUNDARY.sub(" ", text).lower())


def contains_literal(text: str, literal: str) -> bool:
    lit = literal_tokens(literal)
    if not lit:
        return False
    if len(lit) == 1 and re.search(r"[^A-Za-z0-9_]", literal):
        # ".dict()" would reduce to the everyday word "dict"; keep its code shape
        return literal.lower() in text.lower()
    toks = literal_tokens(text)
    n = len(lit)
    if any(toks[i:i + n] == lit for i in range(len(toks) - n + 1)):
        return True
    # Separator dropped entirely, e.g. "legacywrap"
    return n > 1 and "".join(lit) in toks


def find_forbidden(text: str, literals: Iterable[str]) -> List[str]:
    """Forbidden literals present in text, in the order given, without duplicates."""
    found: List[str] = []
    for literal in literals:
        if literal not in found and contains_literal(text, literal):
            found.append(literal)
    return found


def _short_title(node: GraphNode) -> str:
    return node.label.split(":", 1)[-1].strip()


def revival_probability(
    engine: DecisionEngine,
    prompt: str,
    workspace_root: Union[str, Path],
    superseded: GraphNode,
) -> Tuple[float, float]:
    """Probability (among the two real options) that the prompt asks to bring back
    `superseded`, plus the engine latency in ms."""
    from aegis.system1.router import build_context, relative_confidence

    query = ChoiceQuery(
        id="revival_check",
        question="Does this request follow the current architecture decision or revive the superseded one?",
        options=[
            ChoiceOption(
                id="compliant",
                description="a request that does not ask for the old, deprecated approach",
            ),
            ChoiceOption(
                id="revives",
                description=(
                    f"a request asking for the old, deprecated approach "
                    f"({_short_title(superseded)}) instead of the current standard"
                ),
            ),
        ],
        allow_abstention=True,
    )
    res = engine.evaluate_choice(context=build_context(prompt, workspace_root), query=query)
    return relative_confidence(res.probabilities, "revives", {"compliant", "revives"}), res.latency_ms


def strongest_revival(
    engine: Optional[DecisionEngine],
    prompt: str,
    workspace_root: Union[str, Path],
    superseded_nodes: List[GraphNode],
    limit: int = 3,
) -> Optional[Tuple[GraphNode, float]]:
    """Highest revival probability over the superseded nodes in scope, or None
    when no engine is available."""
    if engine is None or not superseded_nodes:
        return None
    best: Optional[Tuple[GraphNode, float]] = None
    for node in superseded_nodes[:limit]:
        try:
            prob, _ = revival_probability(engine, prompt, workspace_root, node)
        except Exception:
            return None
        if best is None or prob > best[1]:
            best = (node, prob)
    return best
