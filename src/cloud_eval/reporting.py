from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from .verifier import VerificationResult


@dataclass
class ActionLog:
    """Single action emitted by an agent during execution."""

    timestamp: float
    action: str
    resource: str
    status: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable representation."""
        return asdict(self)


@dataclass
class ReportMetrics:
    """Normalized metrics for an evaluation run."""

    duration_seconds: float
    step_count: int
    score: Optional[float]
    cost_estimate_usd: float
    error_action_penalty: float

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable representation."""
        return asdict(self)


@dataclass
class EvaluationReport:
    """Structured representation of a run report."""

    task_id: str
    task_name: str
    category_id: Optional[str]
    category_name: Optional[str]
    description: str
    notes: List[str]
    links: List[str]
    actions: List[ActionLog]
    metrics: ReportMetrics
    verification: Optional[VerificationResult]
    started_at: float
    generated_at: float
    endpoint_url: str

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "task_id": self.task_id,
            "task_name": self.task_name,
            "category_id": self.category_id,
            "category_name": self.category_name,
            "description": self.description,
            "notes": self.notes,
            "links": self.links,
            "actions": [action.to_dict() for action in self.actions],
            "metrics": self.metrics.to_dict(),
            "verification": self.verification.model_dump() if self.verification else None,
            "started_at": self.started_at,
            "generated_at": self.generated_at,
            "endpoint_url": self.endpoint_url,
        }
