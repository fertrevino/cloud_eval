# Quick Start: Cloud-Eval Service

## Running the Service

### With Docker Compose (Recommended)

```bash
# Build and start all services
docker compose up --build

# Services available at:
# - Frontend: http://localhost:3000
# - Cloud-Eval Service: http://localhost:5000
# - LocalStack: http://localhost:4566
```

### Local Development

```bash
# Install dependencies
python3 -m pip install -r requirements.txt

# Set environment variables
export ENDPOINT_URL=http://localhost:4566
export CLOUD_EVAL_TASKS_DIR=tasks
export CLOUD_EVAL_REPORT_DIR=reports
export SERVICE_PORT=5000

# Run the service
python3 -m cloud_eval.service

# Service runs at http://localhost:5000
```

## Using the Service

### Via Dashboard
1. Open http://localhost:3000
2. Click the **▶ Run Evaluation** button
3. Watch the status indicator:
   - 🔵 Blue: Running
   - 🟢 Green: Completed
   - 🔴 Red: Failed
4. Reports auto-refresh when complete
5. Click any report to view details

### Via API

#### Start an Evaluation
```bash
curl -X POST http://localhost:5000/api/evaluate \
  -H "Content-Type: application/json" \
  -d '{"agent_name": "openai-llm"}'

# Returns:
# {"run_id": "abc123...", "status": "queued", "message": "..."}
```

#### Check Status
```bash
curl http://localhost:5000/api/status/abc123...

# Returns:
# {
#   "run_id": "abc123...",
#   "status": "running|completed|failed",
#   "created_at": "2025-12-27T00:40:09...",
#   "started_at": "...",
#   "completed_at": null,
#   "error": null,
#   "report_path": null
# }
```

#### List Reports
```bash
curl http://localhost:5000/api/reports

# Returns:
# {
#   "reports": [
#     {"name": "session-id/timestamp/task.json", "modified_at": 1234567890, "size_bytes": 5000},
#     ...
#   ]
# }
```

#### Health Check
```bash
curl http://localhost:5000/health

# Returns:
# {"status": "healthy", "service": "cloud-eval-suite"}
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVICE_PORT` | `5000` | Port to run service on |
| `ENDPOINT_URL` | `http://localhost:4566` | LocalStack endpoint |
| `CLOUD_EVAL_TASKS_DIR` | `tasks` | Path to task definitions |
| `CLOUD_EVAL_REPORT_DIR` | `reports` | Path to store reports |
| `CLOUD_EVAL_AGENT_NAME` | (none) | Agent to use for evaluation |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |

## Features

✅ **RESTful API** - Full control over evaluations via HTTP
✅ **Async Execution** - Background tasks don't block the API
✅ **Status Polling** - Check progress of running evaluations
✅ **Report Management** - List and retrieve completed reports
✅ **Health Checks** - Monitor service availability
✅ **Error Handling** - Detailed error messages and recovery
✅ **Dashboard Integration** - One-click evaluation from UI

## Troubleshooting

### Service won't start
```bash
# Check environment
echo $ENDPOINT_URL
# Should be: http://localhost:4566 (or your LocalStack endpoint)

# Try verbose logging
export LOG_LEVEL=DEBUG
python3 -m cloud_eval.service
```

### Evaluations not completing
```bash
# Check LocalStack is running
curl http://localhost:4566/_localstack/health

# Check service logs
# Docker: docker logs cloud-eval
# Local: Check stderr output
```

### Reports not appearing
```bash
# Check reports directory
ls -la reports/

# Check file permissions
chmod -R a+rwx reports/
```

## Next Steps

- Integrate with CI/CD for automated evaluations
- Add webhook notifications when evaluations complete
- Scale to multiple workers with Celery
- Set up persistent storage (PostgreSQL/Redis)
- Add authentication and rate limiting
- Deploy to Kubernetes for production

See `SERVICE_IMPLEMENTATION.md` for detailed architecture and implementation notes.
