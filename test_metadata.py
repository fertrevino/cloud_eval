#!/usr/bin/env python3
"""Validate task metadata conventions."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

KEBAB_CASE_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)+$")
SNAKE_CASE_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)+$")


def is_kebab_or_snake_case(value: str) -> bool:
    return bool(KEBAB_CASE_RE.match(value) or SNAKE_CASE_RE.match(value))


def load_task_names(tasks_dir: Path) -> list[tuple[Path, str]]:
    results: list[tuple[Path, str]] = []
    for meta_path in tasks_dir.rglob("meta.json"):
        try:
            data = json.loads(meta_path.read_text())
        except Exception:
            continue
        name = data.get("task_name")
        if isinstance(name, str) and name.strip():
            results.append((meta_path, name.strip()))
    return results


def main() -> int:
    tasks_dir = Path(os.getenv("CLOUD_EVAL_TASKS_DIR", "tasks")).resolve()
    if not tasks_dir.exists():
        print(f"Tasks dir not found: {tasks_dir}")
        return 1

    bad = []
    for meta_path, task_name in load_task_names(tasks_dir):
        if is_kebab_or_snake_case(task_name):
            bad.append((meta_path, task_name))

    if bad:
        print("Task names must not be kebab-case or snake_case:")
        for meta_path, task_name in bad:
            print(f"- {meta_path}: {task_name}")
        return 1

    print("All task names look good.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
