"""
OpenAI agent that drives generic AWS tooling for cloud_eval.

It loads the current `description.md`/`meta.json`, builds a prompt describing the job,
and exposes the aws_cli tool defined in `cloud_eval.tools.REGISTRY`. The returned actions are
returned to the runner so they can be written to the log and included in reports.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List

from cloud_eval.logging_config import configure_logging
from cloud_eval.scenario import Scenario, load_scenario
from cloud_eval.tools import REGISTRY, ToolDefinition
from openai import OpenAI

configure_logging()
logger = logging.getLogger("cloud_eval.agents.openai_agent")

ActionRecord = Dict[str, Any]


def _validate_env(env: Dict[str, str]) -> str:
    api_key = env.get("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is required")
    try:
        api_key.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("OPENAI_API_KEY must use ASCII characters") from exc
    return api_key



def _build_messages(scenario: Scenario, raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    system_prompt = (
        "You control AWS resources via a single aws_cli tool. "
        "Only use tool calls to change resource state and never respond directly."
    )
    user_content = f"Task description:\n{scenario.instructions}"
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]


def _resource_label(args: Dict[str, Any], result: Dict[str, Any]) -> str:
    invoked = result.get("invoked_command")
    return invoked or args.get("command") or "aws_cli"


def _record_action(
    tool: ToolDefinition,
    args: Dict[str, Any],
    result: Dict[str, Any],
    llm_trace: Dict[str, Any] | None = None,
) -> ActionRecord:
    status = "ok" if result.get("return_code") == 0 else "error"
    return {
        "timestamp": time.time(),
        "action": tool.name,
        "resource": _resource_label(args, result),
        "status": status,
        "metadata": {
            "args": args,
            "result": result,
            **tool.metadata,
            **({"llm_trace": llm_trace} if llm_trace else {}),
        },
    }


def _assistant_message_payload(message: Any) -> Dict[str, Any]:
    function_call = getattr(message, "function_call", None)
    payload: Dict[str, Any] = {"role": "assistant", "content": message.content or ""}
    if function_call:
        payload["function_call"] = {
            "name": function_call.name,
            "arguments": function_call.arguments or "",
        }
    return payload


def run_agent(scenario_path: Path, env: Dict[str, str]) -> List[ActionRecord]:
    api_key = _validate_env(env)
    openai_client = OpenAI(api_key=api_key)
    model = env["OPENAI_MODEL"]
    scenario = load_scenario(scenario_path)
    raw = json.loads(scenario_path.read_text())
    messages = _build_messages(scenario, raw)
    tools = REGISTRY.descriptions()

    actions: List[ActionRecord] = []
    for _ in range(6):
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Constructed prompt:\n%s", json.dumps(messages, indent=2))
        response = openai_client.chat.completions.create(
            model=model,
            messages=messages,
            functions=tools,
            function_call="auto",
        )
        choice = response.choices[0]
        message = choice.message
        function_call = getattr(message, "function_call", None)
        prompt_snapshot = json.loads(json.dumps(messages))
        assistant_payload = _assistant_message_payload(message)
        logger.debug("Assistant response: %s", json.dumps(assistant_payload, indent=2))
        messages.append(assistant_payload)
        if not function_call:
            logger.debug("No function call returned; finishing interaction")
            break

        args = json.loads(function_call.arguments or "{}")
        tool = REGISTRY.get(function_call.name)
        if not tool:
            logger.warning("Unknown tool requested: %s", function_call.name)
            break

        logger.debug("Invoking tool %s with %s", tool.name, args)
        result = tool.execute(args, env)
        logger.debug("Tool result: %s", json.dumps(result, indent=2))
        messages.append({"role": "function", "name": tool.name, "content": json.dumps(result)})
        actions.append(
            _record_action(
                tool,
                args,
                result,
                llm_trace={"prompt": prompt_snapshot, "assistant": assistant_payload},
            )
        )
    return actions
