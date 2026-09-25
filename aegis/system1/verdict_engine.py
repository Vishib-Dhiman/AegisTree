"""
openJev Verdict v1.4 Decision Engine Implementation for AegisTree.
Wraps the #1 OPEN JevBench model (151M ModernBERT, rlcd) for sub-35ms air-gapped inference.
"""

from __future__ import annotations
import sys
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

from aegis.core.models import (
    ChoiceQuery,
    ChoiceResult,
    ScoreQuery,
    ScoreResult,
    NoulQuery,
    NoulResult
)
from aegis.system1.engine import DecisionEngine, EngineUnavailable

# Ensure local Verdict-open-jev repository is in path
VERDICT_REPO_PATH = Path(__file__).resolve().parent.parent.parent / "Verdict-open-jev"
if str(VERDICT_REPO_PATH) not in sys.path:
    sys.path.insert(0, str(VERDICT_REPO_PATH))

try:
    from rlcd import DecisionEngine as RLCDDecisionEngine, Choice as VChoice, Option as VOption
    HAS_VERDICT = True
except Exception:
    HAS_VERDICT = False


class VerdictDecisionEngine(DecisionEngine):
    """System 1 Decision Engine powered by openJev Verdict v1.4 (heman10x/rlcd-modernbert-151m)."""

    def __init__(self, artifacts_dir: Optional[Path] = None, device: str = "cpu"):
        self.device = device
        self.artifacts_dir = artifacts_dir or (VERDICT_REPO_PATH / "artifacts" / "v2")
        self._engine: Optional[Any] = None
        self._initialize_engine()

    def _initialize_engine(self) -> None:
        if HAS_VERDICT and self.artifacts_dir.exists():
            try:
                self._engine = RLCDDecisionEngine(
                    model_name_or_path=str(self.artifacts_dir),
                    device=self.device
                )
            except Exception as e:
                self._engine = None
        else:
            self._engine = None

    @property
    def engine_name(self) -> str:
        return "openJev Verdict v1.4"

    @property
    def is_airgapped(self) -> bool:
        return True

    def evaluate_choice(self, context: str, query: ChoiceQuery) -> ChoiceResult:
        if self._engine is None:
            raise EngineUnavailable("Verdict engine is unavailable or weights not loaded")

        t0 = time.perf_counter()

        v_options = [
            VOption(id=opt.id, description=opt.description)
            for opt in query.options
        ]
        v_query = VChoice(id=query.id, question=query.question, options=v_options)
        
        batch_result = self._engine.evaluate(context=context, queries=[v_query])
        res = batch_result.results[0]
        lat_ms = (time.perf_counter() - t0) * 1000

        is_abstain = getattr(res, "is_abstention", False) or (res.selected_id == "__insufficient_evidence__")
        
        return ChoiceResult(
            query_id=query.id,
            selected_id=res.selected_id,
            confidence=float(res.selected_probability),
            probabilities={k: float(v) for k, v in res.probabilities.items()},
            is_abstention=is_abstain,
            latency_ms=lat_ms
        )


    def evaluate_score(self, context: str, query: ScoreQuery) -> ScoreResult:
        # Score mapped through discrete candidates
        t0 = time.perf_counter()
        choice_q = ChoiceQuery(
            id=query.id,
            question=query.question,
            options=[
                {"id": f"lvl_{i}", "description": crit}
                for i, crit in enumerate(query.criteria)
            ]
        )
        res = self.evaluate_choice(context, choice_q)
        lat_ms = (time.perf_counter() - t0) * 1000

        # Calculate expected score from probabilities
        expected_score = sum(
            i * res.probabilities.get(f"lvl_{i}", 0.0)
            for i in range(len(query.criteria))
        )
        return ScoreResult(
            query_id=query.id,
            score=expected_score,
            confidence=res.confidence,
            probabilities=res.probabilities,
            latency_ms=lat_ms
        )

    def evaluate_noul(self, context: str, query: NoulQuery) -> NoulResult:
        t0 = time.perf_counter()
        choice_q = ChoiceQuery(
            id=query.id,
            question=query.question,
            options=[
                {"id": "violates", "description": query.criteria_true},
                {"id": "compliant", "description": query.criteria_false}
            ]
        )
        res = self.evaluate_choice(context, choice_q)
        lat_ms = (time.perf_counter() - t0) * 1000

        violates = (res.selected_id == "violates")
        prob = res.probabilities.get("violates", 0.5)

        return NoulResult(
            query_id=query.id,
            violates_constraint=violates,
            probability=prob,
            confidence=res.confidence,
            latency_ms=lat_ms
        )
