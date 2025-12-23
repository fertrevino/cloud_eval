from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Iterable, Optional

from dotenv import load_dotenv
from rich.console import Console

from .agent_config import AgentDefinition, load_agent_definitions, select_agent
from .logging_config import configure_logging
from .runner import EvaluationRunner
from .scenario import load_scenario

console = Console()


def _discover_scenarios(root: Path) -> Iterable[Path]:
    for meta_path in sorted(root.rglob("meta.json")):
        if (meta_path.parent / "verify.py").exists():
            yield meta_path


def run_suite(
    tasks_dir: Path,
    localstack_endpoint: str,
    report_dir: Path,
    agent: Optional[AgentDefinition] = None,
):
    tasks_dir = tasks_dir.resolve()
    scenarios = list(_discover_scenarios(tasks_dir))
    if not scenarios:
        raise SystemExit(f"No scenarios found under {tasks_dir}")

    report_dir.mkdir(parents=True, exist_ok=True)

    for scenario_path in scenarios:
        console.print(f"[blue]Running task[/blue] {scenario_path}")
        scenario = load_scenario(scenario_path)
        runner = EvaluationRunner(
            scenario=scenario,
            scenario_path=scenario_path,
            endpoint_url=localstack_endpoint,
            report_dir=report_dir,
            agent=agent,
        )
        report = runner.run()
        console.print(f"[green]Evaluation complete:[/green] {report}")


def _load_agent() -> Optional[AgentDefinition]:
    agents_path = Path(os.getenv("CLOUD_EVAL_AGENTS_FILE", "agents/agents.yaml"))
    if not agents_path.exists():
        return None
    definitions = load_agent_definitions(agents_path)
    name = os.getenv("CLOUD_EVAL_AGENT_NAME")
    agent = select_agent(definitions, name)
    if agent:
        console.print(f"[magenta]Using agent[/magenta] {agent.name}")
    elif name:
        console.print(f"[yellow]No agent named '{name}' found, running without an agent.[/yellow]")
    return agent


def main() -> None:
    env_path = Path(os.getenv("CLOUD_EVAL_ENV_FILE", ".env"))
    if env_path.exists():
        console.print(f"[cyan]Loading credentials from {env_path}[/cyan]")
        load_dotenv(env_path, override=False)

    configure_logging()
    logger = logging.getLogger("cloud_eval.suite")
    logger.debug("Logging configured; CLOUD_EVAL_DEBUG=%s", os.getenv("CLOUD_EVAL_DEBUG"))

    tasks_dir = Path(os.getenv("CLOUD_EVAL_TASKS_DIR", "tasks"))
    localstack_endpoint = os.getenv("ENDPOINT_URL")
    if not localstack_endpoint:
        raise SystemExit("ENDPOINT_URL is required and must point to LocalStack's endpoint.")
    report_dir = Path(os.getenv("CLOUD_EVAL_REPORT_DIR", "reports"))
    agent = _load_agent()
    if not agent or not agent.module:
        raise SystemExit("No agent module configured; configure CLOUD_EVAL_AGENT_NAME and ensure the catalog defines a module.")

    console.print(f"[magenta]Running suite in[/magenta] {tasks_dir}")
    run_suite(
        tasks_dir=tasks_dir,
        localstack_endpoint=localstack_endpoint,
        report_dir=report_dir,
        agent=agent,
    )


if __name__ == "__main__":
    main()
