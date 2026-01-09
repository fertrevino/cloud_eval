"""Report aggregation utilities."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any


@dataclass
class TaskSummary:
    count: int = 0
    passed: int = 0
    failed: int = 0
    with_score: int = 0
    total_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        avg = self.total_score / self.with_score if self.with_score else 0.0
        pass_rate = self.passed / self.count if self.count else 0.0
        return {
            "count": self.count,
            "passed": self.passed,
            "failed": self.failed,
            "avg_score": round(avg, 4),
            "pass_rate": round(pass_rate, 4),
        }


@dataclass
class Summary:
    total_reports: int = 0
    passed: int = 0
    failed: int = 0
    with_score: int = 0
    total_score: float = 0.0
    by_task: Dict[str, TaskSummary] = field(default_factory=dict)
    by_difficulty: Dict[str, int] = field(default_factory=dict)
    by_model: Dict[str, TaskSummary] = field(default_factory=dict)
    by_model_difficulty: Dict[str, Dict[str, TaskSummary]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        avg_score = self.total_score / self.with_score if self.with_score else 0.0
        pass_rate = self.passed / self.total_reports if self.total_reports else 0.0
        return {
            "total_reports": self.total_reports,
            "passed": self.passed,
            "failed": self.failed,
            "avg_score": round(avg_score, 4),
            "pass_rate": round(pass_rate, 4),
            "by_task": {task: summary.to_dict() for task, summary in self.by_task.items()},
            "by_difficulty": self.by_difficulty,
            "by_model": {model: summary.to_dict() for model, summary in self.by_model.items()},
            "by_model_difficulty": {
                model: {diff: ts.to_dict() for diff, ts in diff_map.items()}
                for model, diff_map in self.by_model_difficulty.items()
            },
        }


def _update_task(container: Dict[str, TaskSummary], key: str, score: float | None, passed: bool) -> None:
    entry = container.setdefault(key, TaskSummary())
    entry.count += 1
    entry.passed += 1 if passed else 0
    entry.failed += 0 if passed else 1
    if score is not None:
        entry.with_score += 1
        entry.total_score += float(score)


def aggregate_reports(report_root: Path) -> Summary:
    """Aggregate all JSON reports under report_root (excluding summary.json)."""
    summary = Summary()
    if not report_root.exists():
        return summary

    for path in report_root.rglob("*.json"):
        if path.name == "summary.json":
            continue
        try:
            data = json.loads(path.read_text())
        except Exception:
            continue

        summary.total_reports += 1
        verification = data.get("verification") or {}
        metrics = data.get("metrics") or {}
        score = metrics.get("score")
        passed = bool(verification.get("passed")) if verification else bool(metrics.get("score"))

        if score is not None:
            summary.with_score += 1
            summary.total_score += float(score)
        if passed:
            summary.passed += 1
        else:
            summary.failed += 1

        task_id = data.get("task_id") or "unknown"
        _update_task(summary.by_task, task_id, score, passed)

        difficulty = data.get("difficulty")
        if isinstance(difficulty, str):
            normalized = difficulty.strip().lower()
            summary.by_difficulty[normalized] = summary.by_difficulty.get(normalized, 0) + 1

        model = data.get("model")
        if isinstance(model, str) and model.strip():
            model_key = model.strip()
            _update_task(summary.by_model, model_key, score, passed)
            if isinstance(difficulty, str):
                diff_key = difficulty.strip().lower()
                model_diff_map = summary.by_model_difficulty.setdefault(model_key, {})
                _update_task(model_diff_map, diff_key, score, passed)

    return summary


def write_summary(report_root: Path, summary: Summary) -> Path:
    """Write summary.json under report_root."""
    report_root.mkdir(parents=True, exist_ok=True)
    target = report_root / "summary.json"
    target.write_text(json.dumps(summary.to_dict(), indent=2))
    return target
