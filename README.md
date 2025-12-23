# cloud_eval

Evaluation harness for AI agents that operate AWS infrastructure inside LocalStack. This repository currently focuses on S3 scenarios, scoring resource correctness, security posture, execution time, step count, action metadata, and error penalties, and exposing everything through reports + a dashboard.

## Getting started

Prereqs: Docker + Docker Compose. The runner image uses the local Python stack defined in `pyproject.toml`.

```bash
# Build images and start containers
docker compose up --build
```

`docker-compose.yml` already sets `ENDPOINT_URL` to `http://localstack:4566`, so the runner will consistently target LocalStack and refuse to touch real AWS.

## Configuration

Drop secrets into `.env` (or set `CLOUD_EVAL_ENV_FILE` to point elsewhere):

```dotenv
CLOUD_EVAL_AGENT_NAME=openai-llm
OPENAI_API_KEY=sk-…
CLOUD_EVAL_LOG_LEVEL=INFO
```

- `CLOUD_EVAL_AGENT_NAME`: must match an entry in `agents/agents.yaml`.
- `OPENAI_API_KEY`: required when using the bundled OpenAI agent; other agents simply need whatever environment they declare.
- `CLOUD_EVAL_LOG_LEVEL`: set to `DEBUG` for verbose prompts/responses, otherwise defaults to `INFO`. Compatibility: `CLOUD_EVAL_DEBUG=1` still toggles `DEBUG`.

Agent definitions live in `agents/agents.yaml`; the runner merges the declared overrides and credentials into the agent’s environment before invoking its `run_agent` function. You can also configure agent-specific metadata (for example `model` for the OpenAI agent) directly in that catalog instead of relying on global `.env` variables.

## Task layout

Each task resides in `tasks/<service>/<category>/<scenario>/` and keeps just the essential files:

```
tasks/<service>/<category>/<scenario>/
├── description.md    # natural-language story shown to the model
├── meta.json         # scenario metadata, tags and notes
└── verify.py         # verification helper to score task performance
```

## Reports & scoring

`reports/` collects one JSON file per run. Each report includes:

- `actions`: CLI invocations the agent issued (timestamps, commands, stdout/stderr, status, traces).
- `metrics`: latency, step count, the verification score, and an `error_action_penalty` deduction (0.02 per failed CLI call).
- `verification`: the `verify.py` output (bucket security map, failures, `score_details.components`, etc.).
- `notes`: propagated from `meta.json` so dashboards can show reference links.

`score_details.components` contains a breakdown of every scoring piece (base score, bonuses, penalty) along with labels and max values, enabling frontend explanations of how the total was computed.

## Dashboard

The dashboard serves the `reports/` directory on port `3000`. Start it after running the suite:

Open http://localhost:3000 to browse past runs, inspect metrics, view each action’s log, and read any scenario notes or reasoning captured during the evaluation.

## Development

- Lint/format: `ruff .`, `black .`
- Pre-commit: `pre-commit install`
