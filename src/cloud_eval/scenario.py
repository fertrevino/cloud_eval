from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class TaskMetadata:
    task_id: str
    task_name: str
    category_id: Optional[str]
    category_name: Optional[str]
    metadata_description: Optional[str]
    author: Optional[str]
    created_at: Optional[str]
    difficulty: "DifficultyLevel"
    tags: List[str]
    notes: List[str] = field(default_factory=list)
    links: List[str] = field(default_factory=list)
    max_steps: Optional[int] = None


@dataclass
class ScenarioScoring:
    weights: Dict[str, float]
    max_time_seconds: Optional[float] = None


@dataclass
class Scenario:
    metadata: TaskMetadata
    tasks: List[Dict[str, Any]]
    scoring: ScenarioScoring
    task_description: str

    @property
    def task_id(self) -> str:
        return self.metadata.task_id

    @property
    def task_name(self) -> str:
        return self.metadata.task_name

    @property
    def category_id(self) -> Optional[str]:
        return self.metadata.category_id

    @property
    def category_name(self) -> Optional[str]:
        return self.metadata.category_name

    @property
    def description(self) -> str:
        return self.metadata.metadata_description or ""

    @property
    def instructions(self) -> str:
        return self.task_description


def _read_description(meta_path: Path) -> str:
    desc_path = meta_path.with_name("description.md")
    if desc_path.exists():
        return desc_path.read_text()
    return ""

class DifficultyLevel(Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


def load_scenario(meta_path: Path) -> Scenario:
    data = json.loads(meta_path.read_text())
    description = _read_description(meta_path)
    scenario_spec: Dict[str, Any] = data.get("scenario") or data
    scoring_spec = scenario_spec.get("scoring", {}) or {}
    raw_difficulty = data.get("difficulty")
    if not raw_difficulty:
        raise ValueError(f"difficulty is required and must be one of {[d.value for d in DifficultyLevel]}")
    try:
        difficulty = DifficultyLevel(str(raw_difficulty).strip().lower())
    except ValueError as exc:
        raise ValueError(f"Invalid difficulty '{raw_difficulty}'. Expected one of {[d.value for d in DifficultyLevel]}") from exc
    metadata = TaskMetadata(
        task_id=data.get("task_id", scenario_spec.get("name", "unnamed")),
        task_name=data.get("task_name") or scenario_spec.get("name") or data.get("task_id", "unnamed"),
        category_id=data.get("category_id"),
        category_name=data.get("category_name"),
        metadata_description=data.get("description", description),
        author=data.get("author"),
        created_at=data.get("created_at"),
        difficulty=difficulty,
        tags=data.get("tags", []),
        notes=data.get("notes", []),
        links=data.get("links", []),
        max_steps=data.get("max_steps"),
    )
    return Scenario(
        metadata=metadata,
        tasks=scenario_spec.get("tasks", []),
        scoring=ScenarioScoring(
            weights=scoring_spec.get("weights", {"resource_correctness": 1.0}),
            max_time_seconds=scoring_spec.get("max_time_seconds"),
        ),
        task_description=description,
    )
