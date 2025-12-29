"""SQS queue creation verification."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import boto3
from botocore.exceptions import ClientError

from cloud_eval.tools import compute_best_practice_tag_score
from cloud_eval.verifier import Verifier, VerificationResult, ScoringWeights, ScoringComponent, ScoringComponentResult

QUEUE_NAME = "cloud-eval-queue"


class SQSQueueVerifier(Verifier):
    """Verifier for SQS queue creation task."""

    scoring_weights = ScoringWeights(
        components={
            "exists": ScoringComponent(
                name="exists",
                label="Queue exists",
                weight=0.8,
                description="Queue was successfully created",
            ),
            "long_polling": ScoringComponent(
                name="long_polling",
                label="Long polling enabled",
                weight=0.1,
                description="ReceiveMessageWaitTimeSeconds > 0",
            ),
            "tags": ScoringComponent(
                name="tags",
                label="Tags applied",
                weight=0.1,
                description="Best-practice tags present on queue",
            ),
        }
    )

    def __init__(self, localstack_endpoint: str, scenario_path: Path | None = None):
        """Initialize verifier.
        
        Args:
            localstack_endpoint: LocalStack endpoint URL
            scenario_path: Path to scenario metadata (unused, for compatibility)
        """
        super().__init__(localstack_endpoint)
        self.scenario_path = scenario_path

    def verify(self) -> VerificationResult:
        """Run verification and return structured result."""
        client = self._build_client()
        checks = self._check_queue(client)
        components = self._compute_components(checks)
        
        total_score = sum(c.value for c in components.values())
        
        return VerificationResult(
            score=round(total_score, 3),
            components=components,
            passed=len(checks.get("errors", [])) == 0,
            errors=checks.get("errors", []),
        )

    def _build_client(self):
        """Build boto3 SQS client."""
        region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
        return boto3.client(
            "sqs",
            endpoint_url=self.endpoint,
            region_name=region,
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "test"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
        )

    def _check_queue(self, client) -> Dict[str, Any]:
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
            result["tag_score"] = compute_best_practice_tag_score(
                tags, cap=self.scoring_weights.components["tags"].weight
            )
        except ClientError as err:
            code = err.response["Error"]["Code"]
            if code in ("AWS.SimpleQueueService.NonExistentQueue", "QueueDoesNotExist"):
                result["errors"].append("queue not found")
            else:
                result["errors"].append(err.response["Error"]["Message"])
        return result

    def _compute_components(self, checks: Dict[str, Any]) -> Dict[str, ScoringComponentResult]:
        """Score each component based on checks."""
        components = {}
        for name, component in self.scoring_weights.components.items():
            if name == "exists":
                value = component.weight if checks["exists"] else 0.0
            elif name == "long_polling":
                value = component.weight if checks["long_polling"] else 0.0
            elif name == "tags":
                value = min(checks.get("tag_score", 0.0), component.weight)
            else:
                value = 0.0

            components[name] = ScoringComponentResult(
                label=component.label,
                description=component.description,
                value=round(value, 3),
                max=component.weight,
            )
        return components


if __name__ == "__main__":
    # Support old CLI interface for compatibility during transition
    import argparse

    parser = argparse.ArgumentParser(description="Verify SQS queue creation")
    parser.add_argument("--scenario-path", type=Path, required=True)
    parser.add_argument("--localstack-endpoint", required=True)
    parser.add_argument("--skip-apply", action="store_true", help="Unused, for parity with runner")
    parser.add_argument("--write-report", type=Path, help="Path to write verification output JSON")
    parser.add_argument("--steps", type=int, default=0)
    args = parser.parse_args()

    verifier = SQSQueueVerifier(args.localstack_endpoint, args.scenario_path)
    result = verifier.verify()
    output = result.model_dump_json(indent=2)
    
    if args.write_report:
        args.write_report.write_text(output)
    else:
        print(output)
