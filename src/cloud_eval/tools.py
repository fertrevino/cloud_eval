from __future__ import annotations

import logging
import os
import shlex
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

logger = logging.getLogger("cloud_eval.tools")

ToolHandler = Callable[[Mapping[str, Any], Mapping[str, str]], Dict[str, Any]]


@dataclass
class ToolDefinition:
    name: str
    description: str
    schema: Dict[str, Any]
    execute: ToolHandler
    metadata: Dict[str, Any] = field(default_factory=dict)


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name} already registered")
        self._tools[tool.name] = tool
        logger.debug("Registered tool %s", tool.name)

    def get(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def tools(self) -> Iterable[ToolDefinition]:
        return self._tools.values()

    def descriptions(self) -> List[Dict[str, Any]]:
        return [
            {"name": tool.name, "description": tool.description, "parameters": tool.schema}
            for tool in self._tools.values()
        ]


REGISTRY = ToolRegistry()

BEST_PRACTICE_TAG_KEYS = [
    "environment",
    "project",
    "service",
    "team",
    "owner",
    "contact",
    "cost_center",
    "billing",
    "application",
    "stack",
    "department",
    "managed_by",
]


def register_tool(
    name: str,
    description: str,
    schema: Dict[str, Any],
    metadata: Optional[Dict[str, Any]] = None,
):
    metadata = metadata or {}

    def decorator(func: ToolHandler) -> ToolHandler:
        REGISTRY.register(
            ToolDefinition(
                name=name,
                description=description,
                schema=schema,
                execute=func,
                metadata=metadata,
            )
        )
        return func

    return decorator


def _build_aws_command(command: str, endpoint: str) -> List[str]:
    if not command.strip():
        raise ValueError("command is required for aws_cli.")

    parts = shlex.split(command)
    cleaned_parts: List[str] = []
    skip_next = False
    for part in parts:
        if skip_next:
            skip_next = False
            continue
        if part == "--endpoint-url":
            skip_next = True
            continue
        if part.startswith("--endpoint-url="):
            continue
        cleaned_parts.append(part)

    if cleaned_parts and cleaned_parts[0].lower() == "aws":
        cleaned_parts = cleaned_parts[1:]

    return ["aws", "--endpoint-url", endpoint] + cleaned_parts



@register_tool(
    name="aws_cli",
    description="Run a generic AWS CLI command against LocalStack.",
    schema={
        "type": "object",
        "properties": {
            "command": {"type": "string"},
        },
        "required": ["command"],
    },
)
def aws_cli_tool(args: Mapping[str, Any], env: Mapping[str, str]) -> Dict[str, Any]:
    endpoint = env.get("ENDPOINT_URL")
    if not endpoint:
        raise ValueError("ENDPOINT_URL is required to run aws_cli.")
    command = args["command"]
    aws_command = _build_aws_command(command, endpoint)
    logger.debug("Executing AWS CLI command: %s", " ".join(aws_command))

    run_env = dict(os.environ)
    run_env.update(env)
    run_env.setdefault("AWS_PAGER", "")
    result = subprocess.run(
        aws_command,
        capture_output=True,
        text=True,
        env=run_env,
    )
    return {
        "command": command,
        "invoked_command": " ".join(aws_command),
        "return_code": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def compute_best_practice_tag_score(
    tags: Mapping[str, Any],
    cap: float,
    split: float = 2.0,
    best_practice_keys: Iterable[str] | None = None,
) -> float:
    """
    Compute a tag score up to `cap`, awarding cap/split per matching best-practice tag key.
    Keys are compared case-insensitively and trimmed for robustness. Defaults to BEST_PRACTICE_TAG_KEYS.
    """
    if cap <= 0:
        return 0.0
    keys = best_practice_keys or BEST_PRACTICE_TAG_KEYS
    per_tag = cap / split if split else cap
    normalized = {str(k).strip().lower() for k in tags.keys()}
    matches = sum(1 for key in keys if key in normalized)
    return min(matches * per_tag, cap)
