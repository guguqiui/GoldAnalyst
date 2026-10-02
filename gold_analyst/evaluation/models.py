"""Stable data structures shared by the case loader and scorer."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class EvaluationCase:
    path: Path
    data: dict[str, Any]

    @property
    def id(self) -> str:
        return self.data["id"]

    @property
    def task(self) -> dict[str, Any]:
        return self.data["task"]

    @property
    def sources(self) -> list[dict[str, Any]]:
        return self.data["sources"]

    @property
    def checks(self) -> list[dict[str, Any]]:
        return self.data["checks"]

    @property
    def rubric(self) -> dict[str, Any]:
        return self.data["rubric"]


@dataclass(frozen=True)
class CheckResult:
    id: str
    dimension: str
    passed: bool
    earned: int
    possible: int
    detail: str
    failure_code: str | None = None
    score_cap: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "dimension": self.dimension,
            "passed": self.passed,
            "earned": self.earned,
            "possible": self.possible,
            "detail": self.detail,
            "failure_code": self.failure_code,
            "score_cap": self.score_cap,
        }

