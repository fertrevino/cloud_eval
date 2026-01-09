from __future__ import annotations

import logging
import os
from importlib import import_module
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from dotenv import load_dotenv
from rich.console import Console

from .agent_config import AgentDefinition, load_agent_definitions, select_agent
from .logging_config import configure_logging
from .runner import EvaluationRunner
from .scenario import load_scenario
from .summary import aggregate_reports, write_summary
from .verifiers_run import VERIFIERS

console = Console()


def _discover_scenarios(root: Path) -> Iterable[Path]:
    """Yield scenario meta paths based on registered verifiers."""
    root = root.resolve()
    for task_id, verifier_cls in VERIFIERS.items():
        try:
            module = import_module(verifier_cls.__module__)
            module_file = getattr(module, "__file__", None)
            if not module_file:
                console.print(f"[yellow]Skipping {task_id}: cannot resolve module file[/yellow]")
                continue
            meta_path = (Path(module_file).parent / "meta.json").resolve()
        except Exception as exc:
            console.print(f"[yellow]Skipping {task_id}: unable to resolve meta path ({exc})[/yellow]")
            continue

        if not meta_path.exists():
            console.print(f"[yellow]Skipping {task_id}: meta.json not found at {meta_path}[/yellow]")
            continue
        if root not in meta_path.parents and meta_path != root:
            console.print(f"[yellow]Skipping {task_id}: meta.json not under tasks_dir ({meta_path})[/yellow]")
            continue

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
        raise SystemExit(f"No scenarios with registered verifiers found under {tasks_dir}")

    report_dir.mkdir(parents=True, exist_ok=True)
    session_label = datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%SZ")

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
        report = runner.run(session_label=session_label)
        console.print(f"[green]Evaluation complete:[/green] {report}")

    try:
        summary = aggregate_reports(report_dir)
        summary_path = write_summary(report_dir, summary)
        console.print(f"[cyan]Summary written to[/cyan] {summary_path}")
    except Exception as exc:
        console.print(f"[yellow]Failed to write summary: {exc}[/yellow]")


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
    logger.debug("Logging configured; LOG_LEVEL=%s", os.getenv("LOG_LEVEL"))

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
