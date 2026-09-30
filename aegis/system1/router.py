"""AegisTree Router: Combines keyword heuristics, Verdict task classifier,
policy overlap scoring, and graph closure.
"""

from __future__ import annotations
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Set, Union
from pydantic import BaseModel

from aegis.core.ast_scoper import ASTScoper, ScopeType
from aegis.core.config import SystemConfig
from aegis.core.models import ChoiceOption, ChoiceQuery, GraphNode, NodeType
from aegis.system1.engine import DecisionEngine, EngineUnavailable
from aegis.system1.graph import MemoryGraph
from aegis.system1.policy_guard import find_forbidden, revival_probability, strongest_revival
from aegis.system1.retrieval import apply_tie_break, needs_tie_break, resolve, retrieve, tie_break
from aegis.system1.verdict_engine import VerdictDecisionEngine


STOPWORDS: Set[str] = {
    "the", "and", "for", "with", "our", "this", "that", "must",
    "from", "into", "you", "your", "are", "was", "not", "adr",
}

# Wording chosen on scripts/data/system1_eval.json (dev split); see scripts/calibrate_system1.py.
TASK_OPTIONS = [
    ChoiceOption(
        id="implement_production",
        description="a request to build, change, or fix a feature in the code",
    ),
    ChoiceOption(
        id="explain_only",
        description="a question asking for an explanation, with no code changes",
    ),
    ChoiceOption(
        id="edit_tests",
        description="a request to write, fix, or change unit tests or test fixtures",
    ),
    ChoiceOption(
        id="write_adr",
        description="a request to create a new decision record, not to change code or explain an existing one",
    ),
]

ABSTAIN_ID = "__insufficient_evidence__"


def build_context(prompt: str, workspace_root: Union[str, Path]) -> str:
    """Context sent to System 1, naming whichever workspace is active."""
    name = Path(workspace_root).resolve().name.replace("_", " ").replace("-", " ")
    return f"Repository: {name}.\nThe user said: {prompt}"


def relative_confidence(probabilities: Dict[str, float], selected_id: str, option_ids: Set[str]) -> float:
    """Probability of selected_id renormalised over the real options.

    Verdict always reserves mass for its insufficient-evidence option, which
    routinely takes 25-40% on short developer prompts and drags the raw top
    probability below any useful threshold. For routing we only need to know
    how decisively the model prefers one real option over the others.
    """
    total = sum(v for k, v in probabilities.items() if k in option_ids)
    if total <= 0:
        return 0.0
    return probabilities.get(selected_id, 0.0) / total


def best_option(probabilities: Dict[str, float], option_ids: Set[str]) -> Optional[str]:
    candidates = {k: v for k, v in probabilities.items() if k in option_ids}
    if not candidates:
        return None
    return max(candidates, key=candidates.get)


class RouteResult(BaseModel):
    status: Literal["ready", "abstained", "blocked"]
    task_type: Literal["implement_production", "explain_only", "edit_tests", "write_adr"]
    task_source: Literal["verdict", "keyword"]
    verdict_task_id: Optional[str] = None
    verdict_confidence: Optional[float] = None
    verdict_latency_ms: Optional[float] = None
    verdict_error: Optional[str] = None
    primary_policy_id: Optional[str] = None
    policy_source: Literal["only_overlap", "verdict", "none"] = "none"
    policy_confidence: Optional[float] = None
    active_policy_ids: List[str] = []
    negative_nodes: List[GraphNode] = []
    habits: List[GraphNode] = []
    excluded_files: List[Dict[str, Any]] = []
    abstain_reason: Optional[str] = None
    draft_adr: Optional[str] = None
    blocked_literal: Optional[str] = None
    blocking_policy_id: Optional[str] = None
    block_method: Optional[Literal["literal", "semantic"]] = None
    retrieval_source: Optional[Literal["verdict", "hybrid", "overlap", "none"]] = None
    retrieval_pick: Optional[str] = None
    retrieval_confidence: Optional[float] = None
    retrieval_latency_ms: Optional[float] = None
    retrieval_scores: Dict[str, Dict[str, float]] = {}
    block_confidence: Optional[float] = None
    revived_policy_id: Optional[str] = None


class BlockResult(BaseModel):
    literal: str
    source_policy_id: str
    reason: str


def check_forbidden_request(
    prompt: str,
    task_type: str,
    active_policies: List[GraphNode],
    negative_nodes: List[GraphNode],
) -> Optional[BlockResult]:
    if task_type != "implement_production":
        return None

    banned = []

    for policy in active_policies:
        for literal in policy.forbidden_literals:
            banned.append({
                "literal": literal,
                "source_policy_id": policy.id,
                "reason": "forbidden by active decision",
            })

    for node in negative_nodes:
        for literal in node.forbidden_literals:
            banned.append({
                "literal": literal,
                "source_policy_id": node.id,
                "reason": "forbidden by superseded decision closure",
            })

    for item in banned:
        if find_forbidden(prompt, [item["literal"]]):
            return BlockResult(
                literal=item["literal"],
                source_policy_id=item["source_policy_id"],
                reason=(
                    f"Action blocked: '{item['literal']}' is forbidden by "
                    f"active policy {item['source_policy_id']}."
                ),
            )

    return None


def apply_keyword_rule(prompt: str) -> Literal["implement_production", "explain_only", "edit_tests", "write_adr"]:
    p = prompt.lower()
    # 1. Prompt contains test or tests AND contains one of update, edit, fix, add, change -> edit_tests
    has_test = "test" in p or "tests" in p
    test_verbs = ["update", "edit", "fix", "add", "change"]
    if has_test and any(v in p for v in test_verbs):
        return "edit_tests"

    # 2. Prompt contains adr AND contains one of write, draft, record, new, create, add, make, propose -> write_adr
    has_adr = "adr" in p
    adr_verbs = ["write", "draft", "record", "new", "create", "add", "make", "propose"]
    if has_adr and any(v in p for v in adr_verbs):
        return "write_adr"

    # 3. Prompt contains one of explain, what is, why, how does, describe AND does not contain one of implement, add a, write a, create -> explain_only
    explain_terms = ["explain", "what is", "why", "how does", "describe"]
    code_terms = ["implement", "add a", "write a", "create"]
    if any(t in p for t in explain_terms) and not any(c in p for c in code_terms):
        return "explain_only"

    # 4. Otherwise -> implement_production
    return "implement_production"


def tokenize_text(text: str) -> Set[str]:
    raw_tokens = set(re.findall(r"[a-z0-9_]{3,}", text.lower())) - STOPWORDS
    tokens = set()
    for tok in raw_tokens:
        tokens.add(tok)
        for part in tok.split("_"):
            if len(part) >= 3 and part not in STOPWORDS:
                tokens.add(part)
    return tokens


class Router:
    """Routes requests using Keyword rules, Verdict classifier, and MemoryGraph."""

    def __init__(
        self,
        graph: MemoryGraph,
        config: Optional[SystemConfig] = None,
        engine: Optional[DecisionEngine] = None,
    ):
        self.graph = graph
        self.config = config or SystemConfig()
        if engine is not None:
            self.engine: Optional[DecisionEngine] = engine
        else:
            try:
                self.engine = VerdictDecisionEngine()
            except Exception:
                self.engine = None

    def route(
        self,
        prompt: str,
        workspace_root: Optional[Union[str, Path]] = None,
        now: Optional[datetime] = None,
    ) -> RouteResult:
        query_time = now or datetime.now(timezone.utc)
        root = Path(workspace_root or self.config.workspace_root)

        # 1. Determine task type (Keyword always computed)
        keyword_task = apply_keyword_rule(prompt)

        verdict_task_id: Optional[str] = None
        verdict_conf: Optional[float] = None
        verdict_lat: Optional[float] = None
        verdict_err: Optional[str] = None

        if self.engine is not None:
            try:
                context = build_context(prompt, root)
                query = ChoiceQuery(
                    id="task_classification",
                    question="What type of action is the user requesting?",
                    options=TASK_OPTIONS,
                    allow_abstention=True,
                )
                t_start = time.perf_counter()
                res = self.engine.evaluate_choice(context=context, query=query)
                verdict_lat = (time.perf_counter() - t_start) * 1000.0
                valid_ids = {o.id for o in TASK_OPTIONS}
                verdict_task_id = best_option(res.probabilities, valid_ids) or res.selected_id
                verdict_conf = relative_confidence(res.probabilities, verdict_task_id, valid_ids)

                if (
                    verdict_task_id in valid_ids
                    and verdict_conf >= self.config.system1_confidence_threshold
                ):
                    task_type = verdict_task_id
                    task_source = "verdict"
                else:
                    task_type = keyword_task
                    task_source = "keyword"
            except EngineUnavailable as eu:
                verdict_err = str(eu)
                task_type = keyword_task
                task_source = "keyword"
            except Exception as ex:
                verdict_err = str(ex)
                task_type = keyword_task
                task_source = "keyword"
        else:
            verdict_err = "Decision model unavailable. Keyword rule used."
            task_type = keyword_task
            task_source = "keyword"

        # 2. Scope exclusions from demo_vault
        excluded_files: List[Dict[str, Any]] = []
        if root.exists():
            for py_file in sorted(root.rglob("*.py")):
                try:
                    scoped = ASTScoper.scope_file(py_file)
                    if scoped.scope in (ScopeType.TEST_FIXTURE, ScopeType.DOCSTRING_COMMENT):
                        rel_path = str(py_file.relative_to(root)) if py_file.is_relative_to(root) else str(py_file)
                        excluded_files.append({
                            "path": f"{root.name}/{rel_path}" if not str(py_file).startswith(root.name) else str(py_file),
                            "scope": scoped.scope.value,
                            "reason": scoped.metadata.get("reason", "Excluded scope"),
                        })
                except Exception:
                    continue

        # 3. Active habits
        active_habits = [n for n in self.graph.active_nodes(query_time) if n.type == NodeType.HABIT]

        # 4. Handle write_adr early
        if task_type == "write_adr":
            today_str = query_time.strftime("%Y-%m-%d")
            title_clean = re.sub(r"[^\w\s-]", "", prompt).strip()
            draft_adr = (
                f"# ADR-0XX: {title_clean}\n\n"
                f"- Status: Proposed\n"
                f"- Date: {today_str}\n"
                f"- Tags:\n\n"
                f"## Decision\n\n"
                f"## Required\n- \n\n"
                f"## Forbidden\n- \n"
            )
            return RouteResult(
                status="ready",
                task_type=task_type,
                task_source=task_source,
                verdict_task_id=verdict_task_id,
                verdict_confidence=verdict_conf,
                verdict_latency_ms=verdict_lat,
                verdict_error=verdict_err,
                primary_policy_id=None,
                policy_source="none",
                policy_confidence=None,
                active_policy_ids=[],
                negative_nodes=[],
                habits=active_habits,
                excluded_files=excluded_files,
                draft_adr=draft_adr,
            )

        # 5. Policy retrieval: token overlap + one Verdict pick over every decision
        decisions = [n for n in self.graph.all_nodes() if n.type == NodeType.ARCHITECTURE_DECISION]
        active_decisions = [n for n in decisions if n.is_active(query_time)]
        superseded_decisions = [n for n in decisions if not n.is_active(query_time)]
        retrieval = retrieve(self.engine, prompt, root, active_decisions, superseded_decisions)
        resolution = resolve(retrieval, self.graph, self.config.system1_retrieval_threshold, query_time)
        if needs_tie_break(resolution):
            tie = tie_break(self.engine, prompt, root, resolution.policies)
            resolution = apply_tie_break(resolution, tie, self.config.system1_confidence_threshold)
        retrieval_fields = dict(
            retrieval_source=resolution.source,
            retrieval_pick=retrieval.pick,
            retrieval_confidence=retrieval.pick_confidence if retrieval.pick else None,
            retrieval_latency_ms=retrieval.latency_ms,
            retrieval_scores=retrieval.scores(),
        )

        # Abstain: no decision overlaps and Verdict did not confidently pick one
        if not resolution.policies:
            if task_type == "edit_tests":
                return RouteResult(
                    status="ready",
                    task_type=task_type,
                    task_source=task_source,
                    verdict_task_id=verdict_task_id,
                    verdict_confidence=verdict_conf,
                    verdict_latency_ms=verdict_lat,
                    verdict_error=verdict_err,
                    primary_policy_id=None,
                    policy_source="none",
                    policy_confidence=None,
                    active_policy_ids=[],
                    negative_nodes=[],
                    habits=active_habits,
                    excluded_files=excluded_files,
                    abstain_reason=None,
                    **retrieval_fields,
                )

            checked_ids = [d.id for d in active_decisions]
            if resolution.verdict_says_none:
                abstain_msg = (
                    f"No accepted architecture decision covers request: '{prompt}'. "
                    f"System 1 picked 'none of these' (p={retrieval.pick_confidence:.2f}) "
                    f"over active decisions: {checked_ids}."
                )
            else:
                abstain_msg = (
                    f"No accepted architecture decision overlaps request: '{prompt}'. "
                    f"Checked active decisions: {checked_ids}."
                )
            return RouteResult(
                status="abstained",
                task_type=task_type,
                task_source=task_source,
                verdict_task_id=verdict_task_id,
                verdict_confidence=verdict_conf,
                verdict_latency_ms=verdict_lat,
                verdict_error=verdict_err,
                primary_policy_id=None,
                policy_source="none",
                policy_confidence=None,
                active_policy_ids=[],
                negative_nodes=[],
                habits=active_habits,
                excluded_files=excluded_files,
                abstain_reason=abstain_msg,
                **retrieval_fields,
            )

        active_policy_ids = [n.id for n in resolution.policies]
        primary_policy_id = resolution.primary.id
        policy_source: Literal["only_overlap", "verdict", "none"] = (
            "verdict" if resolution.source in ("verdict", "hybrid") else "only_overlap"
        )
        policy_conf: Optional[float] = resolution.confidence

        # 6. Closure (one hop supersedes edges from active_policy_ids to target nodes)
        negative_nodes: List[GraphNode] = []
        superseded_by: Dict[str, str] = {}
        for pol_id in active_policy_ids:
            for succ in self.graph.successors(pol_id, relation="supersedes"):
                if succ.id not in superseded_by:
                    superseded_by[succ.id] = pol_id
                    negative_nodes.append(succ)
        revival_candidate = resolution.revival_candidate
        if revival_candidate is not None and revival_candidate.id not in superseded_by:
            superseded_by[revival_candidate.id] = primary_policy_id
            negative_nodes.append(revival_candidate)

        # 7. Check for forbidden literal requests in production implementation
        active_policy_nodes = resolution.policies
        block = check_forbidden_request(
            prompt=prompt,
            task_type=task_type,
            active_policies=active_policy_nodes,
            negative_nodes=negative_nodes,
        )
        if block:
            return RouteResult(
                status="blocked",
                task_type=task_type,
                task_source=task_source,
                verdict_task_id=verdict_task_id,
                verdict_confidence=verdict_conf,
                verdict_latency_ms=verdict_lat,
                verdict_error=verdict_err,
                primary_policy_id=primary_policy_id,
                policy_source=policy_source,
                policy_confidence=policy_conf,
                active_policy_ids=active_policy_ids,
                negative_nodes=negative_nodes,
                habits=active_habits,
                excluded_files=excluded_files,
                abstain_reason=block.reason,
                blocked_literal=block.literal,
                blocking_policy_id=block.source_policy_id,
                block_method="literal",
                **retrieval_fields,
            )

        # 8. Paraphrased requests for a superseded decision ("the old wrap cipher")
        if task_type == "implement_production":
            revival = None
            if revival_candidate is not None and self.engine is not None:
                try:
                    prob, _ = revival_probability(self.engine, prompt, root, revival_candidate)
                    if prob >= self.config.system1_revival_assist_threshold:
                        revival = (revival_candidate, prob)
                except Exception:
                    revival = None
            if revival is None:
                strongest = strongest_revival(self.engine, prompt, root, negative_nodes)
                if strongest and strongest[1] >= self.config.system1_revival_threshold:
                    revival = strongest
            if revival:
                revived, prob = revival
                enforcing_id = superseded_by[revived.id]
                return RouteResult(
                    status="blocked",
                    task_type=task_type,
                    task_source=task_source,
                    verdict_task_id=verdict_task_id,
                    verdict_confidence=verdict_conf,
                    verdict_latency_ms=verdict_lat,
                    verdict_error=verdict_err,
                    primary_policy_id=primary_policy_id,
                    policy_source=policy_source,
                    policy_confidence=policy_conf,
                    active_policy_ids=active_policy_ids,
                    negative_nodes=negative_nodes,
                    habits=active_habits,
                    excluded_files=excluded_files,
                    abstain_reason=(
                        f"Action blocked: request asks for superseded decision {revived.id} "
                        f"(System 1 revival probability {prob:.2f}), replaced by active policy {enforcing_id}."
                    ),
                    blocking_policy_id=enforcing_id,
                    block_method="semantic",
                    block_confidence=prob,
                    revived_policy_id=revived.id,
                    **retrieval_fields,
                )

        return RouteResult(
            status="ready",
            task_type=task_type,
            task_source=task_source,
            verdict_task_id=verdict_task_id,
            verdict_confidence=verdict_conf,
            verdict_latency_ms=verdict_lat,
            verdict_error=verdict_err,
            primary_policy_id=primary_policy_id,
            policy_source=policy_source,
            policy_confidence=policy_conf,
            active_policy_ids=active_policy_ids,
            negative_nodes=negative_nodes,
            habits=active_habits,
            excluded_files=excluded_files,
            abstain_reason=None,
            **retrieval_fields,
        )
