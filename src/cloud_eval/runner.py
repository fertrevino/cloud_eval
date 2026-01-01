from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from importlib import import_module
from pathlib import Path
from typing import Dict, List, Optional

from rich.console import Console

from . import __version__
from .agent_config import AgentDefinition
from .reporting import ActionLog, EvaluationReport, ReportMetrics
from .scenario import Scenario
from .verifier import STATIC_VERIFIER_CLASSES, ScoreDetailComponent, VerificationResult

console = Console()
logger = logging.getLogger("cloud_eval.runner")


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

    def _run_verification(self, steps: int) -> Optional[VerificationResult]:
        try:
            verifier_cls = STATIC_VERIFIER_CLASSES[self.scenario.task_id]
            verifier = verifier_cls(self.localstack_endpoint, self.scenario_path)
            result = verifier.run()
            return result
        except Exception:
            logger.exception("Verifier failed for task %s", self.scenario.task_id)
            return None

    def _score(self, actions: List[ActionLog], verification: Optional[VerificationResult]) -> ReportMetrics:
        timing = verification.score_details.timing if verification else None
        duration = timing.duration_seconds if timing else 0.0
        action_count = len(actions)

        metrics = ReportMetrics(
            duration_seconds=duration,
            step_count=action_count,
            score=verification.score if verification else None,
            cost_estimate_usd=0.0,
            error_action_penalty=0.0,
        )
        error_actions = sum(1 for action in actions if action.status == "error")
        penalty = round(error_actions * 0.02, 3)
        metrics.error_action_penalty = penalty
        if metrics.score is not None:
            metrics.score = max(0.0, metrics.score - penalty)
        return metrics

    def _create_run_dir(self, label: Optional[str] = None) -> Path:
        # Use a readable, filesystem-safe timestamp for the run directory (e.g. 2023-10-17T03-21-59Z)
        label = label or datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%SZ")
        run_dir = self.report_root / label
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def run(self, session_label: Optional[str] = None) -> Path:
        run_dir = self._create_run_dir(session_label)
        task_label = self.scenario.task_name or self.scenario.task_id or "task"
        console.print(
            f"[bold green]cloud-eval[/bold green] v{__version__} starting task: {task_label}"
        )
        console.print(f"Ensuring LocalStack is reachable at {self.localstack_endpoint}")

        actions = self._run_agent()
        verification = self._run_verification(len(actions))
        metrics = self._score(actions, verification)
        logger.debug("Completed scenario metrics: %s", metrics)
        verification_payload: Optional[VerificationResult] = None
        if verification:
            verification_payload = verification.model_copy(deep=True)
            components = verification_payload.score_details.components
            # Seed score_details with the main components so the UI can render a full breakdown.
            for name, comp in verification_payload.components.items():
                components.setdefault(
                    name,
                    ScoreDetailComponent(
                        label=comp.label,
                        value=comp.value,
                        max=comp.max,
                        description=comp.description,
                    ),
                )
            if metrics.error_action_penalty:
                components["error_action_penalty"] = ScoreDetailComponent(
                    label="Penalty (-0.02 per error action)",
                    value=-metrics.error_action_penalty,
                    max=None,
                )

        report = EvaluationReport(
            task_id=self.scenario.task_id,
            task_name=task_label,
            category_id=self.scenario.category_id,
            category_name=self.scenario.category_name,
            description=self.scenario.description,
            notes=self.scenario.metadata.notes,
            links=self.scenario.metadata.links,
            actions=actions,
            metrics=metrics,
            verification=verification_payload,
            started_at=(
                verification_payload.score_details.timing.started_at
                if verification_payload and verification_payload.score_details.timing
                else time.time()
            ),
            generated_at=time.time(),
            endpoint_url=self.localstack_endpoint,
        )

        timestamp = int(time.time())
        slug = task_label.replace(" ", "-").lower()
        report_path = run_dir / f"{slug}-{timestamp}.json"
        report_path.write_text(json.dumps(report.to_dict(), indent=2))
        console.print(f"[green]Report written to[/green] {report_path}")
        return report_path
