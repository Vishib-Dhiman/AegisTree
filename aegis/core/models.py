"""
Core Data Models for AegisTree Sovereign Second Brain.
Defines Graph Nodes, Bi-Temporal Edges, Bounded Typed Primitives, and Leaf Contexts.
"""

from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class NodeType(str, Enum):
    IDENTITY = "identity"
    HABIT = "habit"
    CODE_CONVENTION = "code_convention"
    ARCHITECTURE_DECISION = "architecture_decision"
    PROJECT_STATE = "project_state"
    SECURITY_POLICY = "security_policy"
    DEPRECATED_PATTERN = "deprecated_pattern"


class EpistemicStatus(str, Enum):
    HYPOTHESIS = "hypothesis"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DEPRECATED = "deprecated"
    ABANDONED = "abandoned"


class GraphNode(BaseModel):
    id: str
    type: NodeType
    label: str
    description: str = ""
    epistemic_status: EpistemicStatus = EpistemicStatus.ACTIVE
    metadata: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)
    valid_from: Optional[datetime] = None
    superseded_at: Optional[datetime] = None
    required_literals: List[str] = Field(default_factory=list)
    forbidden_literals: List[str] = Field(default_factory=list)

    def is_active(self, query_time: Optional[datetime] = None) -> bool:
        t = query_time or datetime.now(timezone.utc)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        if self.epistemic_status != EpistemicStatus.ACTIVE:
            return False
        if self.valid_from is not None:
            vf = self.valid_from
            if vf.tzinfo is None:
                vf = vf.replace(tzinfo=timezone.utc)
            if vf > t:
                return False
        if self.superseded_at is not None:
            sa = self.superseded_at
            if sa.tzinfo is None:
                sa = sa.replace(tzinfo=timezone.utc)
            if sa <= t:
                return False
        return True


class BiTemporalEdge(BaseModel):
    source: str
    target: str
    relation: str  # e.g., "supersedes", "requires", "enforces", "deprecates"
    system_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))  # recorded_at
    valid_from: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    deprecated_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def is_active(self, query_time: Optional[datetime] = None) -> bool:
        t = query_time or datetime.now(timezone.utc)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        if self.valid_from is not None:
            vf = self.valid_from
            if vf.tzinfo is None:
                vf = vf.replace(tzinfo=timezone.utc)
            if t < vf:
                return False
        if self.deprecated_at is not None:
            da = self.deprecated_at
            if da.tzinfo is None:
                da = da.replace(tzinfo=timezone.utc)
            if t >= da:
                return False
        return True


# -------------------------------------------------------------
# Bounded Primitives for System 1 (Verdict / Jev)
# -------------------------------------------------------------

class ChoiceOption(BaseModel):
    id: str
    description: str
    is_deprecated: bool = False


class ChoiceQuery(BaseModel):
    id: str
    question: str
    options: List[ChoiceOption]
    allow_abstention: bool = True


class ChoiceResult(BaseModel):
    query_id: str
    selected_id: str
    confidence: float
    probabilities: Dict[str, float]
    is_abstention: bool = False
    latency_ms: float = 0.0


class ScoreQuery(BaseModel):
    id: str
    question: str
    criteria: List[str]  # e.g. Level 1 to 5


class ScoreResult(BaseModel):
    query_id: str
    score: float
    confidence: float
    probabilities: Dict[str, float]
    latency_ms: float = 0.0


class NoulQuery(BaseModel):
    id: str
    question: str
    criteria_true: str = "Violates policy or constraint"
    criteria_false: str = "Compliant with policy"


class NoulResult(BaseModel):
    query_id: str
    violates_constraint: bool
    probability: float
    confidence: float
    latency_ms: float = 0.0


# -------------------------------------------------------------
# Leaf Context Compiler Model
# -------------------------------------------------------------

class LeafContext(BaseModel):
    target_project: str
    active_habits: List[str] = Field(default_factory=list)
    active_conventions: List[str] = Field(default_factory=list)
    architectural_directives: List[str] = Field(default_factory=list)
    negative_constraints: List[str] = Field(default_factory=list)  # FORBIDDEN patterns
    token_count_estimate: int = 0
    system1_latency_ms: float = 0.0
