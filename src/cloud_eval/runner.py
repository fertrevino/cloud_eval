from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from importlib import import_module
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import Console

from . import __version__
from .agent_config import AgentDefinition
from .scenario import Scenario

console = Console()
logger = logging.getLogger("cloud_eval.runner")


@dataclass
class ActionLog:
    timestamp: float
    action: str
    resource: str
    status: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class EvaluationRunner:
    def __init__(
        self,
        scenario: Scenario,
        scenario_path: Path,
        endpoint_url: str,
        report_dir: Path,
        agent: Optional[AgentDefinition] = None,
    ):
        self.scenario = scenario
        self.scenario_path = scenario_path
        self.localstack_endpoint = endpoint_url
        self.report_root = report_dir
        self.agent = agent
        self.report_root.mkdir(parents=True, exist_ok=True)

    def _assemble_agent_env(self) -> Dict[str, str]:
        env = {**os.environ}
        env.update(
            {
            "SCENARIO_PATH": str(self.scenario_path),
            "ENDPOINT_URL": self.localstack_endpoint,
        }
        )
        if self.agent:
            env.update(self.agent.env)
            for dest, source in self.agent.credentials_env.items():
                value = os.getenv(source)
                if value:
                    env[dest] = value
                else:
                    console.print(
                        f"[yellow]Agent {self.agent.name} missing credential env '{source}'; skipping value.[/yellow]"
            )
            logger.debug("Missing credential env %s for agent %s", source, self.agent.name)
            if self.agent.model:
                env["OPENAI_MODEL"] = self.agent.model
        logger.debug("Assembled agent env keys: %s", sorted(env.keys()))
        return env

    def _run_agent(self) -> List[ActionLog]:
        if not self.agent or not self.agent.module:
            console.print(
                "[yellow]No agent module configured; skipping agent execution and continuing to evaluation.[/yellow]"
            )
            logger.debug("Skipping agent: agent or module not configured")
            return []

        env = self._assemble_agent_env()
        console.print(f"[cyan]Running agent module:[/cyan] {self.agent.module}")
        try:
            return self._run_agent_module(env)
        except Exception as exc:
            console.print(f"[red]Agent module failed:[/red] {exc}")
            logger.exception("Agent module failure")
            return []

    def _run_agent_module(self, env: Dict[str, str]) -> List[ActionLog]:
        module_name = self.agent.module
        module = import_module(module_name)
        run_fn = getattr(module, "run_agent", None)
        if not callable(run_fn):
            raise RuntimeError(f"Agent module {module_name} does not expose run_agent()")

        result = run_fn(self.scenario_path, env)
        logs: List[ActionLog] = []
        for entry in result:
            logs.append(
                ActionLog(
                    timestamp=entry.get("timestamp", time.time()),
                    action=entry.get("action", "unknown"),
                    resource=entry.get("resource", "unknown"),
                    status=entry.get("status", "unknown"),
                    metadata=entry.get("metadata", {}),
                )
            )
        return logs

    def _run_verification(self, steps: int) -> Optional[Dict[str, Any]]:
        verify_path = self.scenario_path.with_name("verify.py")
        if not verify_path.exists():
            return None

        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as tmp_file:
            report_path = Path(tmp_file.name)

            cmd = [
                "python",
                str(verify_path),
                "--scenario-path",
                str(self.scenario_path),
                "--localstack-endpoint",
                self.localstack_endpoint,
                "--skip-apply",
                "--write-report",
                str(report_path),
                "--steps",
                str(steps),
            ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            console.print(
                "[yellow]Verification script failed; check container logs for details.[/yellow]"
            )
            logger.debug("Verification stdout: %s", result.stdout)
            logger.debug("Verification stderr: %s", result.stderr)

        verification = None
        if report_path.exists():
            try:
                verification = json.loads(report_path.read_text())
            except json.JSONDecodeError as exc:
                logger.error("Unable to parse verification output: %s", exc)
            finally:
                report_path.unlink(missing_ok=True)
        return verification

    def _score(
        self, actions: List[ActionLog], start_time: float, verification: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        duration = time.monotonic() - start_time
        action_count = len(actions)
        max_time = self.scenario.scoring.max_time_seconds
        max_steps = self.scenario.scoring.max_steps

        latency_score = 1.0 if not max_time else max(0.0, min(1.0, 1.0 - duration / max_time))
        step_score = 1.0 if not max_steps else max(0.0, min(1.0, 1.0 - (action_count / max_steps)))

        metrics = {
            "resource_correctness": None,
            "security": None,
            "duration_seconds": duration,
            "step_count": action_count,
            "score": latency_score * (self.scenario.scoring.weights.get("latency", 0.0))
            + step_score * (self.scenario.scoring.weights.get("steps", 0.0)),
            "cost_estimate_usd": 0.0,
        }
        if verification:
            metrics["resource_correctness"] = verification.get("resource_correctness")
            metrics["security"] = verification.get("security")
            if verification.get("score") is not None:
                metrics["score"] = verification["score"]
        if verification and verification.get("score") is not None:
            metrics["score"] = verification["score"]
        error_actions = sum(1 for action in actions if action.status == "error")
        penalty = round(error_actions * 0.02, 3)
        metrics["error_action_penalty"] = penalty
        if metrics["score"] is not None:
            metrics["score"] = max(0.0, metrics["score"] - penalty)
        return metrics

    def _create_run_dir(self, label: Optional[str] = None) -> Path:
        # Use a readable, filesystem-safe timestamp for the run directory (e.g. 2023-10-17T03-21-59Z)
        label = label or datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%SZ")
        run_dir = self.report_root / label
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def run(self, session_label: Optional[str] = None) -> Path:
        run_dir = self._create_run_dir(session_label)
        start_time = time.monotonic()
        task_label = self.scenario.task_name or self.scenario.task_id or "task"
        console.print(
            f"[bold green]cloud-eval[/bold green] v{__version__} starting task: {task_label}"
        )
        console.print(f"Ensuring LocalStack is reachable at {self.localstack_endpoint}")

        actions = self._run_agent()
        verification = self._run_verification(len(actions))
        metrics = self._score(actions, start_time, verification)
        logger.debug("Completed scenario metrics: %s", metrics)
        penalty = metrics.get("error_action_penalty")
        if verification and penalty is not None:
            components = verification.get("score_details", {}).get("components")
            if isinstance(components, dict):
                components["error_action_penalty"] = {
                    "label": "Penalty (–0.02 per error action)",
                    "value": penalty,
                    "max": None,
                }

        report = {
            "task_id": self.scenario.task_id,
            "task_name": task_label,
            "category_id": self.scenario.category_id,
            "category_name": self.scenario.category_name,
            "description": self.scenario.description,
            "notes": self.scenario.metadata.notes,
            "links": self.scenario.metadata.links,
            "reports": [],
            "actions": [action.__dict__ for action in actions],
            "metrics": metrics,
            "verification": verification,
            "started_at": start_time,
            "generated_at": time.monotonic(),
            "endpoint_url": self.localstack_endpoint,
        }

        timestamp = int(time.time())
        slug = task_label.replace(" ", "-").lower()
        report_path = run_dir / f"{slug}-{timestamp}.json"
        report_path.write_text(json.dumps(report, indent=2))
        console.print(f"[green]Report written to[/green] {report_path}")
        return report_path
