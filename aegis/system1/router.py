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
from aegis.system1.verdict_engine import VerdictDecisionEngine


STOPWORDS: Set[str] = {
    "the", "and", "for", "with", "our", "this", "that", "must",
    "from", "into", "you", "your", "are", "was", "not", "adr",
}

TASK_OPTIONS = [
    ChoiceOption(
        id="implement_production",
        description="a request to add or change production code that stores or rotates session tokens",
    ),
    ChoiceOption(
        id="explain_only",
        description="a request for an explanation with no file edits",
    ),
    ChoiceOption(
        id="edit_tests",
        description="a request to change files under the tests directory",
    ),
    ChoiceOption(
        id="write_adr",
        description="a request to record a new architecture decision rather than edit code",
    ),
]


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

    prompt_lower = prompt.lower()
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
        if item["literal"].lower() in prompt_lower:
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
                context = f"Repository: Northwind session vault.\nThe user said: {prompt}"
                query = ChoiceQuery(
                    id="task_classification",
                    question="What type of action is the user requesting?",
                    options=TASK_OPTIONS,
                    allow_abstention=True,
                )
                t_start = time.perf_counter()
                res = self.engine.evaluate_choice(context=context, query=query)
                verdict_lat = (time.perf_counter() - t_start) * 1000.0
                verdict_task_id = res.selected_id
                verdict_conf = res.confidence

                valid_ids = {"implement_production", "explain_only", "edit_tests", "write_adr"}
                if (
                    not res.is_abstention
                    and res.selected_id in valid_ids
                    and res.confidence >= self.config.system1_confidence_threshold
                ):
                    task_type = res.selected_id
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

        # 5. Policy overlap search over ACTIVE decisions
        active_decisions = [
            n for n in self.graph.active_nodes(query_time)
            if n.type == NodeType.ARCHITECTURE_DECISION
        ]

        prompt_tokens = tokenize_text(prompt)
        scored_policies = []
        for dec in active_decisions:
            dec_tags = {t.lower() for t in dec.tags}
            dec_label_tokens = tokenize_text(dec.label)
            dec_forbidden_tokens = set()
            for f in dec.forbidden_literals:
                dec_forbidden_tokens |= tokenize_text(f)
            dec_required_tokens = set()
            for r in dec.required_literals:
                dec_required_tokens |= tokenize_text(r)

            score = (
                len(dec_tags & prompt_tokens)
                + len(dec_label_tokens & prompt_tokens)
                + len(dec_forbidden_tokens & prompt_tokens)
                + len(dec_required_tokens & prompt_tokens)
            )
            if score > 0:
                scored_policies.append((score, dec))

        # Check for abstention: zero active decisions with score > 0
        if not scored_policies:
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
                )

            checked_ids = [d.id for d in active_decisions]
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
            )

        # Sort descending by score, tiebreak with valid_from descending
        scored_policies.sort(
            key=lambda x: (x[0], x[1].valid_from.timestamp() if x[1].valid_from else 0),
            reverse=True,
        )
        active_policy_ids = [dec.id for _, dec in scored_policies]

        primary_policy_id: str
        policy_source: Literal["only_overlap", "verdict", "none"]
        policy_conf: Optional[float] = None

        if len(scored_policies) == 1:
            primary_policy_id = scored_policies[0][1].id
            policy_source = "only_overlap"
        else:
            # Two or more: try Verdict if available
            candidates = [dec for _, dec in scored_policies[:5]]
            winner_node = candidates[0]
            policy_source = "only_overlap"

            if self.engine is not None:
                try:
                    options = [
                        ChoiceOption(
                            id=c.id,
                            description=f"the binding decision titled {c.label}. {c.description[:120]}",
                        )
                        for c in candidates
                    ]
                    q = ChoiceQuery(
                        id="policy_selection",
                        question="Which architectural decision primarily governs this request?",
                        options=options,
                        allow_abstention=True,
                    )
                    vres = self.engine.evaluate_choice(context=context, query=q)
                    candidate_ids = {c.id for c in candidates}
                    if (
                        not vres.is_abstention
                        and vres.selected_id in candidate_ids
                        and vres.confidence >= self.config.system1_confidence_threshold
                    ):
                        primary_policy_id = vres.selected_id
                        policy_source = "verdict"
                        policy_conf = vres.confidence
                    else:
                        primary_policy_id = winner_node.id
                except Exception:
                    primary_policy_id = winner_node.id
            else:
                primary_policy_id = winner_node.id

        # 6. Closure (one hop supersedes edges from active_policy_ids to target nodes)
        negative_nodes: List[GraphNode] = []
        seen_neg = set()
        for pol_id in active_policy_ids:
            for succ in self.graph.successors(pol_id, relation="supersedes"):
                if succ.id not in seen_neg:
                    seen_neg.add(succ.id)
                    negative_nodes.append(succ)

        # 7. Check for forbidden literal requests in production implementation
        active_policy_nodes = [dec for _, dec in scored_policies]
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
        )
