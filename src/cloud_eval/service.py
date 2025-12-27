"""FastAPI service for cloud-eval suite evaluation."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .agent_config import AgentDefinition, load_agent_definitions, select_agent
from .logging_config import configure_logging
from .suite import run_suite

logger = logging.getLogger("cloud_eval.service")

# Initialize logging
configure_logging()

# In-memory task store (in production, use a database)
task_store: Dict[str, Dict[str, Any]] = {}


class EvaluateRequest(BaseModel):
    """Request to start a new evaluation."""

    agent_name: Optional[str] = None


class EvaluateResponse(BaseModel):
    """Response for evaluation request."""

    run_id: str
    status: str
    message: str


class TaskStatus(BaseModel):
    """Task status response."""

    run_id: str
    status: str
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    report_path: Optional[str] = None


class ReportSummary(BaseModel):
    """Summary of a report file."""

    name: str
    modified_at: float
    size_bytes: int


def _load_config() -> tuple[Path, str, Path]:
    """Load configuration from environment."""
    tasks_dir = Path(os.getenv("CLOUD_EVAL_TASKS_DIR", "tasks")).resolve()
    localstack_endpoint = os.getenv("ENDPOINT_URL")
    if not localstack_endpoint:
        raise RuntimeError("ENDPOINT_URL is required")
    report_dir = Path(os.getenv("CLOUD_EVAL_REPORT_DIR", "reports")).resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    return tasks_dir, localstack_endpoint, report_dir


def _load_agent_for_service() -> Optional[AgentDefinition]:
    """Load agent configuration from environment."""
    agents_path = Path(os.getenv("CLOUD_EVAL_AGENTS_FILE", "agents/agents.yaml"))
    if not agents_path.exists():
        return None
    definitions = load_agent_definitions(agents_path)
    name = os.getenv("CLOUD_EVAL_AGENT_NAME")
    return select_agent(definitions, name)


async def _run_evaluation_task(run_id: str, tasks_dir: Path, endpoint: str, report_dir: Path, agent: Optional[AgentDefinition]) -> None:
    """Background task to run the evaluation suite."""
    task_store[run_id]["status"] = "running"
    task_store[run_id]["started_at"] = datetime.utcnow().isoformat()

    try:
        # Run in thread pool to avoid blocking event loop
        loop = asyncio.get_event_loop()
        
        # Create session-specific report directory
        session_id = run_id
        session_report_dir = report_dir / session_id
        
        await loop.run_in_executor(
            None,
            run_suite,
            tasks_dir,
            endpoint,
            session_report_dir,
            agent,
        )
        
        task_store[run_id]["status"] = "completed"
        task_store[run_id]["report_path"] = str(session_report_dir)
        logger.info(f"Evaluation {run_id} completed successfully")
    except Exception as exc:
        task_store[run_id]["status"] = "failed"
        task_store[run_id]["error"] = str(exc)
        logger.exception(f"Evaluation {run_id} failed")
    finally:
        task_store[run_id]["completed_at"] = datetime.utcnow().isoformat()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Cloud Eval Suite Service",
        description="API for triggering and monitoring cloud-eval evaluations",
        version="1.0.0",
    )

    # Load configuration at startup
    try:
        tasks_dir, endpoint, report_dir = _load_config()
        agent = _load_agent_for_service()
    except RuntimeError as exc:
        logger.error(f"Failed to load configuration: {exc}")
        raise

    @app.get("/health")
    async def health() -> Dict[str, str]:
        """Health check endpoint."""
        return {"status": "healthy", "service": "cloud-eval-suite"}

    @app.post("/api/evaluate", response_model=EvaluateResponse)
    async def evaluate(request: EvaluateRequest) -> EvaluateResponse:
        """Trigger a new evaluation run."""
        run_id = str(uuid.uuid4())
        
        # Create task entry
        task_store[run_id] = {
            "status": "queued",
            "created_at": datetime.utcnow().isoformat(),
            "started_at": None,
            "completed_at": None,
            "error": None,
            "report_path": None,
        }
        
        logger.info(f"Queued evaluation run: {run_id}")
        
        # Schedule background task (non-blocking)
        # Note: In production, use Celery or similar for proper task queuing
        asyncio.create_task(
            _run_evaluation_task(run_id, tasks_dir, endpoint, report_dir, agent)
        )
        
        return EvaluateResponse(
            run_id=run_id,
            status="queued",
            message=f"Evaluation {run_id} queued for execution",
        )

    @app.get("/api/status/{run_id}", response_model=TaskStatus)
    async def status(run_id: str) -> TaskStatus:
        """Get the status of an evaluation run."""
        if run_id not in task_store:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        
        task = task_store[run_id]
        return TaskStatus(
            run_id=run_id,
            status=task["status"],
            created_at=task["created_at"],
            started_at=task["started_at"],
            completed_at=task["completed_at"],
            error=task["error"],
            report_path=task["report_path"],
        )

    @app.get("/api/reports")
    async def list_reports() -> Dict[str, Any]:
        """List all available evaluation reports."""
        reports = []
        
        try:
            if not report_dir.exists():
                return {"reports": []}
            
            for report_file in sorted(report_dir.rglob("*.json")):
                try:
                    stat = report_file.stat()
                    reports.append(
                        {
                            "name": str(report_file.relative_to(report_dir)),
                            "modified_at": stat.st_mtime,
                            "size_bytes": stat.st_size,
                        }
                    )
                except OSError:
                    continue
        except Exception as exc:
            logger.warning(f"Failed to list reports: {exc}")
        
        return {"reports": sorted(reports, key=lambda x: x["modified_at"], reverse=True)}

    @app.get("/api/runs")
    async def list_runs() -> Dict[str, Any]:
        """List all evaluation runs and their statuses."""
        runs = []
        for run_id, task in sorted(task_store.items(), key=lambda x: x[1]["created_at"], reverse=True):
            runs.append(
                {
                    "run_id": run_id,
                    "status": task["status"],
                    "created_at": task["created_at"],
                    "started_at": task["started_at"],
                    "completed_at": task["completed_at"],
                    "error": task["error"],
                }
            )
        return {"runs": runs}

    return app


if __name__ == "__main__":
    import uvicorn

    app = create_app()
    port = int(os.getenv("SERVICE_PORT", "5000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
