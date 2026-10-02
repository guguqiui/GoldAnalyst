"""Load evaluation cases and score GoldAnalyst runs without model calls."""

from .loader import load_case, load_cases, match_case_for_run
from .models import EvaluationCase
from .scorer import score_run
from .storage import save_evaluation

__all__ = [
    "EvaluationCase",
    "load_case",
    "load_cases",
    "match_case_for_run",
    "save_evaluation",
    "score_run",
]
