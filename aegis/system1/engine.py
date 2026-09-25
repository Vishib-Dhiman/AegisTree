"""
Abstract Decision Engine Interface for AegisTree.
Defines the contract for non-autoregressive decision models (openJev Verdict, Cloud Jev, etc.).
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from aegis.core.models import ChoiceQuery, ChoiceResult, ScoreQuery, ScoreResult, NoulQuery, NoulResult


class EngineUnavailable(Exception):
    """Raised when the local decision engine is missing, uninitialized, or cannot load weights."""
    pass


class DecisionEngine(ABC):
    """Abstract interface for System 1 typed decision evaluations."""

    @abstractmethod
    def evaluate_choice(self, context: str, query: ChoiceQuery) -> ChoiceResult:
        """Evaluates a categorical choice over a bounded set of options."""
        pass

    @abstractmethod
    def evaluate_score(self, context: str, query: ScoreQuery) -> ScoreResult:
        """Evaluates an ordinal or continuous score (e.g., Level 1-5)."""
        pass

    @abstractmethod
    def evaluate_noul(self, context: str, query: NoulQuery) -> NoulResult:
        """Evaluates a binary constraint or policy violation."""
        pass

    @property
    @abstractmethod
    def engine_name(self) -> str:
        """Returns the name and version of the decision engine."""
        pass

    @property
    @abstractmethod
    def is_airgapped(self) -> bool:
        """True if the engine operates completely locally with 0 external network packets."""
        pass
