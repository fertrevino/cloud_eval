"""SNS topic creation verification."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import boto3
from botocore.exceptions import ClientError

from cloud_eval.tools import compute_best_practice_tag_score
from cloud_eval.verifier import Verifier, VerificationResult, ScoringWeights, ScoringComponent, ScoringComponentResult

TOPIC_NAME = "cloud-eval-topic"


class SNSTopicVerifier(Verifier):
    """Verifier for SNS topic creation task."""

    scoring_weights = ScoringWeights(
        components={
            "exists": ScoringComponent(
                name="exists",
                label="Topic exists",
                weight=0.9,
                description="Topic was successfully created",
            ),
            "tags": ScoringComponent(
                name="tags",
                label="Tags applied",
                weight=0.1,
                description="Best-practice tags present on topic",
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
        checks = self._check_topic(client)
        components = self._compute_components(checks)
        
        total_score = sum(c.value for c in components.values())
        score_details = {
            "components": {
                name: {"label": comp.label, "value": comp.value, "max": comp.max}
                for name, comp in components.items()
            }
        }

        return VerificationResult(
            score=round(total_score, 3),
            components=components,
            passed=len(checks.get("errors", [])) == 0,
            errors=checks.get("errors", []),
            score_details=score_details,
        )

    def _build_client(self):
        """Build boto3 SNS client."""
        region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
        return boto3.client(
            "sns",
            endpoint_url=self.endpoint,
            region_name=region,
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "test"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
        )

    def _check_topic(self, client) -> Dict[str, Any]:
        """Return topic metadata; handle missing topic gracefully."""
        result: Dict[str, Any] = {
            "exists": False,
            "tags_applied": False,
            "tag_score": 0.0,
            "topic_arn": None,
            "attributes": {},
            "tags": {},
            "errors": [],
        }
        try:
            # List topics to find the one we created
            topics_resp = client.list_topics()
            topics = topics_resp.get("Topics", [])
            
            # Find topic by name in ARN
            topic_arn = None
            for topic in topics:
                if TOPIC_NAME in topic["TopicArn"]:
                    topic_arn = topic["TopicArn"]
                    break
            
            if not topic_arn:
                result["errors"].append("topic not found")
                return result
            
            result["topic_arn"] = topic_arn
            result["exists"] = True
            
            # Get topic attributes
            attrs_resp = client.get_topic_attributes(TopicArn=topic_arn)
            attrs = attrs_resp.get("Attributes", {})
            result["attributes"] = attrs
            
            # Get topic tags
            try:
                tags_resp = client.list_tags_for_resource(ResourceArn=topic_arn)
                tags_list = tags_resp.get("Tags") or []
                tags = {
                    tag.get("Key", ""): tag.get("Value", "")
                    for tag in tags_list
                    if tag.get("Key")
                }
            except ClientError:
                tags = {}

            result["tags"] = tags
            result["tags_applied"] = len(tags) > 0
            result["tag_score"] = compute_best_practice_tag_score(
                tags, cap=self.scoring_weights.components["tags"].weight
            )
        except ClientError as err:
            result["errors"].append(err.response["Error"]["Message"])
        return result

    def _compute_components(self, checks: Dict[str, Any]) -> Dict[str, ScoringComponentResult]:
        """Score each component based on checks."""
        components = {}
        for name, component in self.scoring_weights.components.items():
            if name == "exists":
                value = component.weight if checks["exists"] else 0.0
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

    parser = argparse.ArgumentParser(description="Verify SNS topic creation")
    parser.add_argument("--scenario-path", type=Path, required=True)
    parser.add_argument("--localstack-endpoint", required=True)
    parser.add_argument("--skip-apply", action="store_true", help="Unused, for parity with runner")
    parser.add_argument("--write-report", type=Path, help="Path to write verification output JSON")
    parser.add_argument("--steps", type=int, default=0)
    args = parser.parse_args()

    verifier = SNSTopicVerifier(args.localstack_endpoint, args.scenario_path)
    result = verifier.verify()
    output = result.model_dump_json(indent=2)
    
    if args.write_report:
        args.write_report.write_text(output)
    else:
        print(output)
