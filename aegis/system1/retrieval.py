"""Policy retrieval: which architecture decision governs a request.

Two signals, both local:
1. Token overlap between the prompt and each decision's tags, title and literals.
2. Verdict retrieval: one forward pass that picks among every decision in the
   workspace (active and superseded) plus an explicit "none of these" option.
   This finds decisions the prompt never names ("make sessions last forever"
   -> the session TTL decision) and lets System 1 abstain on requests no
   decision covers. No embedding model is involved.
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from aegis.core.models import ChoiceOption, ChoiceQuery, GraphNode
from aegis.system1.engine import DecisionEngine

NONE_ID = "__no_decision__"
# Verdict's calibrator covers up to 25 options; one slot is NONE_ID.
MAX_RETRIEVAL_OPTIONS = 24


def short_title(node: GraphNode) -> str:
    """'ADR-014: Persist and seal session tokens' -> 'Persist and seal session tokens'."""
    return node.label.split(":", 1)[-1].strip()


def overlap_score(prompt_tokens: set, decision: GraphNode) -> int:
    from aegis.system1.router import tokenize_text

    tags = {t.lower() for t in decision.tags}
    label_tokens = tokenize_text(decision.label)
    forbidden_tokens = set()
    for literal in decision.forbidden_literals:
        forbidden_tokens |= tokenize_text(literal)
    required_tokens = set()
    for literal in decision.required_literals:
        required_tokens |= tokenize_text(literal)
    return (
        len(tags & prompt_tokens)
        + len(label_tokens & prompt_tokens)
        + len(forbidden_tokens & prompt_tokens)
        + len(required_tokens & prompt_tokens)
    )


def rank_by_overlap(prompt: str, decisions: List[GraphNode]) -> List[Tuple[int, GraphNode]]:
    """Decisions with any overlap, best first; ties go to the newer decision."""
    from aegis.system1.router import tokenize_text

    prompt_tokens = tokenize_text(prompt)
    scored = [(overlap_score(prompt_tokens, d), d) for d in decisions]
    scored = [(s, d) for s, d in scored if s > 0]
    scored.sort(
        key=lambda x: (x[0], x[1].valid_from.timestamp() if x[1].valid_from else 0),
        reverse=True,
    )
    return scored


def retrieval_options(decisions: List[GraphNode]) -> List[ChoiceOption]:
    options = [
        ChoiceOption(id=d.id, description=f"a request about {short_title(d).lower()}")
        for d in decisions
    ]
    options.append(
        ChoiceOption(id=NONE_ID, description="a request about something none of these decisions cover")
    )
    return options


@dataclass
class Retrieval:
    overlap: List[Tuple[int, GraphNode]] = field(default_factory=list)
    pick: Optional[str] = None
    pick_confidence: float = 0.0
    probabilities: Dict[str, float] = field(default_factory=dict)
    latency_ms: Optional[float] = None
    error: Optional[str] = None

    def scores(self) -> Dict[str, Dict[str, float]]:
        """Per-decision {overlap, verdict} for telemetry."""
        out: Dict[str, Dict[str, float]] = {}
        for score, node in self.overlap:
            out.setdefault(node.id, {})["overlap"] = score
        for node_id, prob in self.probabilities.items():
            if node_id != NONE_ID:
                out.setdefault(node_id, {})["verdict"] = round(prob, 4)
        return out


def retrieve(
    engine: Optional[DecisionEngine],
    prompt: str,
    workspace_root: Union[str, Path],
    active: List[GraphNode],
    superseded: List[GraphNode],
) -> Retrieval:
    """Overlap ranking over active decisions, plus a Verdict pick over all decisions."""
    from aegis.system1.router import best_option, relative_confidence

    result = Retrieval(overlap=rank_by_overlap(prompt, active))
    if engine is None or not (active or superseded):
        return result

    candidates = active + superseded
    if len(candidates) > MAX_RETRIEVAL_OPTIONS:
        # Keep the decisions the prompt already overlaps with, then active before superseded
        overlap_ids = {d.id for _, d in rank_by_overlap(prompt, candidates)}
        candidates.sort(key=lambda d: (d.id not in overlap_ids, d not in active))
        candidates = candidates[:MAX_RETRIEVAL_OPTIONS]

    options = retrieval_options(candidates)
    option_ids = {o.id for o in options}
    query = ChoiceQuery(
        id="policy_retrieval",
        question="Which architecture decision governs this request?",
        options=options,
        allow_abstention=True,
    )
    try:
        t0 = time.perf_counter()
        # No repository name here: a workspace called 'sqlalchemy' pulls every request
        # toward the decision titled 'SQLAlchemy 2.0 ...'
        res = engine.evaluate_choice(context=f"The user said: {prompt}", query=query)
        result.latency_ms = (time.perf_counter() - t0) * 1000.0
    except Exception as ex:
        result.error = str(ex)
        return result

    total = sum(v for k, v in res.probabilities.items() if k in option_ids) or 1.0
    result.probabilities = {k: v / total for k, v in res.probabilities.items() if k in option_ids}
    result.pick = best_option(res.probabilities, option_ids)
    if result.pick:
        result.pick_confidence = relative_confidence(res.probabilities, result.pick, option_ids)
    return result


@dataclass
class Resolution:
    policies: List[GraphNode]
    primary: Optional[GraphNode]
    source: str  # "verdict" | "hybrid" | "overlap" | "none"
    revival_candidate: Optional[GraphNode] = None
    verdict_says_none: bool = False
    confidence: Optional[float] = None


def resolve(retrieval: Retrieval, graph, threshold: float, at=None) -> Resolution:
    """Combine Verdict's pick with overlap.

    - Confident pick of an active decision: it leads, overlap matches follow.
    - Confident pick of a superseded decision: its active successor leads and the
      superseded one becomes a revival candidate for the policy guard.
    - Otherwise overlap alone, exactly as before retrieval existed.
    An empty policy list means abstain.
    """
    overlap_nodes = [node for _, node in retrieval.overlap]
    confident = retrieval.pick is not None and retrieval.pick_confidence >= threshold

    lead: Optional[GraphNode] = None
    revival: Optional[GraphNode] = None
    if confident and retrieval.pick != NONE_ID:
        picked = graph.node(retrieval.pick)
        if picked is not None and picked.is_active(at):
            lead = picked
        elif picked is not None:
            lead = graph.active_successor(picked.id, at)
            revival = picked if lead is not None else None

    if lead is not None:
        policies = [lead] + [n for n in overlap_nodes if n.id != lead.id]
        return Resolution(policies, lead, "verdict", revival, confidence=retrieval.pick_confidence)

    if overlap_nodes:
        return Resolution(overlap_nodes, overlap_nodes[0], "overlap")
    return Resolution([], None, "none", verdict_says_none=confident and retrieval.pick == NONE_ID)


def needs_tie_break(resolution: Resolution) -> bool:
    return resolution.source == "overlap" and len(resolution.policies) > 1


def tie_break(
    engine: Optional[DecisionEngine],
    prompt: str,
    workspace_root: Union[str, Path],
    candidates: List[GraphNode],
) -> Optional[Tuple[str, float]]:
    """Verdict's choice among several overlapping decisions, as (id, confidence).

    A different question from `retrieve`: full titles and descriptions, top five
    candidates only. Short titles are better for finding a decision among all of
    them; the fuller text separates decisions that share vocabulary
    ("rotate session token" overlaps both token sealing and token telemetry).
    """
    from aegis.system1.router import best_option, build_context, relative_confidence

    if engine is None:
        return None
    top = candidates[:5]
    options = [
        ChoiceOption(id=c.id, description=f"the binding decision titled {c.label}. {c.description[:120]}")
        for c in top
    ]
    query = ChoiceQuery(
        id="policy_selection",
        question="Which architectural decision primarily governs this request?",
        options=options,
        allow_abstention=True,
    )
    try:
        res = engine.evaluate_choice(context=build_context(prompt, workspace_root), query=query)
    except Exception:
        return None
    ids = {c.id for c in top}
    pick = best_option(res.probabilities, ids)
    return (pick, relative_confidence(res.probabilities, pick, ids)) if pick else None


def apply_tie_break(resolution: Resolution, tie: Optional[Tuple[str, float]], threshold: float) -> Resolution:
    if tie is None or tie[1] < threshold:
        return resolution
    best = next((n for n in resolution.policies if n.id == tie[0]), None)
    if best is None:
        return resolution
    policies = [best] + [n for n in resolution.policies if n.id != best.id]
    return Resolution(policies, best, "hybrid", confidence=tie[1])
