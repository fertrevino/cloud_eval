from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import yaml


@dataclass
class AgentDefinition:
    name: str
    module: Optional[str]
    env: Dict[str, str] = field(default_factory=dict)
    credentials_env: Dict[str, str] = field(default_factory=dict)
    model: Optional[str] = None


def _load_agent(entry: Dict[str, str]) -> AgentDefinition:
    return AgentDefinition(
        name=entry["name"],
        module=entry.get("module"),
        env=entry.get("env", {}),
        credentials_env=entry.get("credentials_env", {}),
        model=entry.get("model"),
    )


def load_agent_definitions(path: Path) -> List[AgentDefinition]:
    raw = yaml.safe_load(path.read_text())
    agents = raw.get("agents", [])
    return [_load_agent(entry) for entry in agents]


def select_agent(definitions: Iterable[AgentDefinition], name: Optional[str]) -> Optional[AgentDefinition]:
    if not name:
        return next(iter(definitions), None)
    for entry in definitions:
        if entry.name == name:
            return entry
    return None
