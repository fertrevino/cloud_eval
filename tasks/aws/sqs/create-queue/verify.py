from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

import boto3
from botocore.exceptions import ClientError


QUEUE_NAME = "cloud-eval-queue"
WEIGHTS = {
    "exists": 0.8,
    "long_polling": 0.1,
    "tags": 0.1,
}

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


def build_client(endpoint: str):
    region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    return boto3.client(
        "sqs",
        endpoint_url=endpoint,
        region_name=region,
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "test"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
    )


def compute_tag_score(tags: Dict[str, Any]) -> float:
    """Award up to the tag weight, split across best-practice tags (case-insensitive)."""
    normalized_keys = {str(k).strip().lower() for k in tags.keys()}
    matches = sum(1 for key in BEST_PRACTICE_TAG_KEYS if key in normalized_keys)
    cap = WEIGHTS["tags"]
    if cap <= 0:
        return 0.0
    per_tag = cap / 2  # 0.05 when cap is 0.1; two best-practice tags hits the cap
    return min(matches * per_tag, cap)


def check_queue(client) -> Dict[str, Any]:
    """Return queue metadata; handle missing queue gracefully."""
    result: Dict[str, Any] = {
        "exists": False,
        "long_polling": False,
        "tags_applied": False,
        "tag_score": 0.0,
        "queue_url": None,
        "attributes": {},
        "tags": {},
        "errors": [],
    }
    try:
        url = client.get_queue_url(QueueName=QUEUE_NAME)["QueueUrl"]
        result["queue_url"] = url
        result["exists"] = True
        attrs_resp = client.get_queue_attributes(
            QueueUrl=url,
            AttributeNames=["ReceiveMessageWaitTimeSeconds"],
        )
        attrs = attrs_resp.get("Attributes", {})
        result["attributes"] = attrs
        wait_time = int(attrs.get("ReceiveMessageWaitTimeSeconds", "0"))
        result["long_polling"] = wait_time > 0

        tags_resp = client.list_queue_tags(QueueUrl=url)
        tags = tags_resp.get("Tags", {}) or {}
        result["tags"] = tags
        result["tags_applied"] = len(tags) > 0
        result["tag_score"] = compute_tag_score(tags)
    except ClientError as err:
        code = err.response["Error"]["Code"]
        if code in ("AWS.SimpleQueueService.NonExistentQueue", "QueueDoesNotExist"):
            result["errors"].append("queue not found")
        else:
            result["errors"].append(err.response["Error"]["Message"])
    return result


def score_checks(checks: Dict[str, Any]) -> Dict[str, Any]:
    components = {
        "exists": {
            "label": "Queue exists",
            "value": WEIGHTS["exists"] if checks["exists"] else 0.0,
            "max": WEIGHTS["exists"],
        },
        "long_polling": {
            "label": "Long polling enabled",
            "value": WEIGHTS["long_polling"] if checks["long_polling"] else 0.0,
            "max": WEIGHTS["long_polling"],
        },
        "tags": {
            "label": "Tags applied",
            "value": min(checks.get("tag_score", 0.0), WEIGHTS["tags"]),
            "max": WEIGHTS["tags"],
        },
    }
    score = sum(component["value"] for component in components.values())
    security_score = (
        components["long_polling"]["value"] + components["tags"]["value"]
    ) / (WEIGHTS["long_polling"] + WEIGHTS["tags"])
    return {
        "score": round(score, 3),
        "resource_correctness": round(score, 3),
        "security": round(security_score, 3),
        "score_details": {"components": components},
    }


def run(args: argparse.Namespace) -> Dict[str, Any]:
    client = build_client(args.localstack_endpoint)
    checks = check_queue(client)
    scores = score_checks(checks)
    report = {
        "task_id": "aws-sqs-create-queue",
        "queue_name": QUEUE_NAME,
        "checks": checks,
        **scores,
    }
    return report


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Verify SQS queue creation")
    parser.add_argument("--scenario-path", required=True)
    parser.add_argument("--localstack-endpoint", required=True)
    parser.add_argument("--skip-apply", action="store_true", help="Unused, for parity with runner")
    parser.add_argument("--write-report", help="Path to write verification output JSON")
    parser.add_argument("--steps", type=int, default=0)
    args = parser.parse_args(argv)

    report = run(args)
    output = json.dumps(report, indent=2)
    if args.write_report:
        Path(args.write_report).write_text(output)
    else:
        print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
