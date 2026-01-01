"""
Standardized verification interface and data models.

All task verifiers inherit from Verifier and return VerificationResult.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Optional

from pydantic import BaseModel, Field, field_validator


class ScoringComponent(BaseModel):
    """Single scoring component (e.g., 'exists', 'tags', 'encryption')."""

    name: str
    label: str
    weight: float = Field(..., ge=0.0, le=1.0)
    description: str = ""
    value: float = Field(default=0.0, ge=0.0, le=1.0)


class ScoringWeights(BaseModel):
    """Weights definition for a task's scoring breakdown."""

    components: Dict[str, ScoringComponent]

    @field_validator("components")
    @classmethod
    def weights_sum_to_one(cls, v: Dict[str, ScoringComponent]) -> Dict[str, ScoringComponent]:
        """Validate that all weights sum to 1.0 (within tolerance)."""
        total = sum(comp.weight for comp in v.values())
        if not (0.99 <= total <= 1.01):  # Allow small floating-point rounding
            raise ValueError(
                f"Scoring weights must sum to 1.0, got {total:.3f}. "
                f"Components: {[f'{k}={comp.weight}' for k, comp in v.items()]}"
            )
        return v

    def to_dict(self) -> Dict[str, float]:
        """Return simple {name: weight} dict for backwards compatibility."""
        return {name: comp.weight for name, comp in self.components.items()}


class ScoringComponentResult(BaseModel):
    """Result/score for a single component in verification."""

    label: str = Field(description="Human-readable label for this component")
    description: str = Field(default="", description="Detailed description of what this component checks")
    value: float = Field(..., ge=0.0, le=1.0, description="Actual score achieved (0.0–1.0)")
    max: float = Field(..., ge=0.0, le=1.0, description="Maximum possible weight for this component")


class TimingInfo(BaseModel):
    """Timing metadata for a verifier step."""

    started_at: float = Field(description="Wall-clock start time (epoch seconds)")
    ended_at: float = Field(description="Wall-clock end time (epoch seconds)")
    duration_seconds: float = Field(description="Elapsed seconds (end-start)")


class ScoreDetailComponent(BaseModel):
    """Additional score component not part of the primary scoring."""

    label: str
    value: float
    max: Optional[float] = None
    description: str = ""


class ScoreDetails(BaseModel):
    """Structured container for auxiliary scoring and timing details."""

    timing: Optional[TimingInfo] = Field(default=None)
    components: Dict[str, ScoreDetailComponent] = Field(default_factory=dict)


class VerificationResult(BaseModel):
    """Standard verification output returned by all Verifier implementations."""

    score: float = Field(..., ge=0.0, le=1.0, description="Overall score 0.0–1.0")
    components: Dict[str, ScoringComponentResult] = Field(
        description="Breakdown by component: {name: ScoringComponentResult}"
    )
    passed: bool = Field(description="True if score >= 0.5 (or task-specific threshold)")
    errors: list[str] = Field(default_factory=list, description="List of errors encountered")
    score_details: ScoreDetails = Field(default_factory=ScoreDetails, description="Auxiliary scoring metadata")


class VerificationConfig(BaseModel):
    """Configuration for running a verifier."""

    localstack_endpoint: str
    scenario_path: str
    steps: int = 0

    @property
    def scenario_path_obj(self) -> Path:
        return Path(self.scenario_path)


class Verifier(ABC):
    """Base class for all task verifiers."""

    # Subclasses must define this
    scoring_weights: ScoringWeights

    def __init__(self, localstack_endpoint: str):
        """Initialize verifier with LocalStack endpoint."""
        self.endpoint = localstack_endpoint

    def run(self) -> VerificationResult:
        """Execute verification and record timing metadata."""
        started_at = time.time()
        result = self.verify()
        ended_at = time.time()
        duration = ended_at - started_at
        result.score_details.timing = TimingInfo(
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=round(duration, 3),
        )
        return result

    @abstractmethod
    def verify(self) -> VerificationResult:
        """Run verification and return structured result."""
        pass


# Static map of task_id to verifier classes (importable modules under tasks/)
from tasks.aws.s3.simple_bucket.verify import S3BucketVerifier  # noqa: E402
from tasks.aws.sqs.create_queue.verify import SQSQueueVerifier  # noqa: E402
from tasks.aws.sns.create_topic.verify import SNSTopicVerifier  # noqa: E402

STATIC_VERIFIER_CLASSES: Dict[str, type[Verifier]] = {
    "cloud-eval-s3-simple-bucket": S3BucketVerifier,
    "aws-sqs-create-queue": SQSQueueVerifier,
    "aws-sns-create-topic": SNSTopicVerifier,
}
