"""S3 application logs bucket verification."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List

import boto3
from botocore.exceptions import ClientError

from cloud_eval.tools import compute_best_practice_tag_score
from cloud_eval.verifier import (
    Verifier,
    VerificationResult,
    ScoringWeights,
    ScoringComponent,
    ScoringComponentResult,
)

logger = logging.getLogger("cloud_eval.verify.s3.application_logs")

EXPECTED_BUCKET_NAME = "application-logs-6fa7fc53-2c28-4d8f-9603-35271d573d3a"
EXPECTED_REGION = "us-east-1"
RETENTION_MIN_DAYS = 170  # allow slight wiggle room for "6 months"
RETENTION_MAX_DAYS = 190
PUBLIC_ACCESS_BLOCK_KEYS = (
    "BlockPublicAcls",
    "IgnorePublicAcls",
    "BlockPublicPolicy",
    "RestrictPublicBuckets",
)
DEFAULT_ENCRYPTION_ALGORITHMS = {"AES256", "aws:kms"}


class S3ApplicationLogsVerifier(Verifier):
    """Verifier for application logs bucket with retention requirements."""

    scoring_weights = ScoringWeights(
        components={
            "exists_and_region": ScoringComponent(
                name="exists_and_region",
                label="Bucket exists in us-east-1",
                weight=0.5,
                description=f"Bucket {EXPECTED_BUCKET_NAME} exists in {EXPECTED_REGION}",
            ),
            "retention_policy": ScoringComponent(
                name="retention_policy",
                label="6-month retention",
                weight=0.3,
                description="Lifecycle rule deletes objects after ~6 months",
            ),
            "block_public_access": ScoringComponent(
                name="block_public_access",
                label="Public access block",
                weight=0.1,
                description="All block public access settings enabled",
            ),
            "default_encryption": ScoringComponent(
                name="default_encryption",
                label="Default encryption",
                weight=0.05,
                description="Server-side encryption configured",
            ),
            "best_practice_tags": ScoringComponent(
                name="best_practice_tags",
                label="Tags applied",
                weight=0.05,
                description="Best-practice tags present",
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
        bucket_info = self._collect_bucket_info(client)
        errors = self._collect_errors(bucket_info)
        components = self._compute_components(bucket_info)

        total_score = sum(component.value for component in components.values())

        return VerificationResult(
            score=round(total_score, 3),
            components=components,
            passed=len(errors) == 0,
            errors=errors,
        )

    def _build_client(self):
        """Build boto3 S3 client."""
        return boto3.client(
            "s3",
            endpoint_url=self.endpoint,
            region_name=EXPECTED_REGION,
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "test"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
        )

    def _get_bucket_location(self, client, bucket: str) -> str | None:
        """Get bucket region."""
        try:
            response = client.get_bucket_location(Bucket=bucket)
        except ClientError as exc:
            logger.debug("Could not determine bucket %s location: %s", bucket, exc)
            return None
        region = response.get("LocationConstraint")
        return "us-east-1" if not region else region

    def _get_bucket_tags(self, client, bucket: str) -> Dict[str, str]:
        """Return tags as a key/value mapping."""
        try:
            tag_resp = client.get_bucket_tagging(Bucket=bucket)
            tag_set = tag_resp.get("TagSet", [])
            return {
                tag.get("Key", ""): tag.get("Value", "")
                for tag in tag_set
                if tag.get("Key")
            }
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code == "NoSuchTagSet":
                return {}
            raise

    def _get_public_access_block(self, client, bucket: str) -> Dict[str, Any]:
        """Get public access block configuration."""
        try:
            response = client.get_public_access_block(Bucket=bucket)
            configuration = response.get("PublicAccessBlockConfiguration", {})
            return {
                "configuration": configuration,
                "all_true": all(configuration.get(key) for key in PUBLIC_ACCESS_BLOCK_KEYS),
            }
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code == "NoSuchPublicAccessBlockConfiguration":
                return {"configuration": {}, "all_true": False}
            raise

    def _bucket_has_default_encryption(self, client, bucket: str) -> bool:
        """Check if bucket has default encryption enabled."""
        try:
            response = client.get_bucket_encryption(Bucket=bucket)
            rules = response.get("ServerSideEncryptionConfiguration", {}).get("Rules", [])
            for rule in rules:
                algorithm = rule.get("ApplyServerSideEncryptionByDefault", {}).get("SSEAlgorithm")
                if algorithm in DEFAULT_ENCRYPTION_ALGORITHMS:
                    return True
            return False
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in (
                "ServerSideEncryptionConfigurationNotFoundError",
                "EncryptionConfigurationNotFoundError",
            ):
                return False
            raise

    def _get_lifecycle_rules(self, client, bucket: str) -> List[Dict[str, Any]]:
        """Fetch lifecycle rules if configured."""
        try:
            response = client.get_bucket_lifecycle_configuration(Bucket=bucket)
            return response.get("Rules", [])
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in ("NoSuchLifecycleConfiguration", "NoSuchLifecycleConfigurationFault"):
                return []
            raise

    def _extract_retention_days(self, rules: List[Dict[str, Any]]) -> int | None:
        """Find the shortest expiration (in days) among enabled lifecycle rules."""
        days: list[int] = []
        for rule in rules:
            if str(rule.get("Status", "")).lower() != "enabled":
                continue
            expiration = rule.get("Expiration") or {}
            exp_days = expiration.get("Days")
            if isinstance(exp_days, int):
                days.append(exp_days)
            noncurrent = rule.get("NoncurrentVersionExpiration") or {}
            noncurrent_days = noncurrent.get("NoncurrentDays")
            if isinstance(noncurrent_days, int):
                days.append(noncurrent_days)
        if not days:
            return None
        return min(days)

    def _collect_bucket_info(self, client) -> Dict[str, Any]:
        """Gather all evaluation attributes for the target bucket."""
        info: Dict[str, Any] = {
            "exists": False,
            "region": None,
            "region_matches": False,
            "tags": {},
            "tag_score": 0.0,
            "public_access_block": {},
            "public_block_enabled": False,
            "default_encryption_enabled": False,
            "lifecycle_rules": [],
            "retention_days": None,
            "retention_ok": False,
            "errors": [],
        }

        try:
            client.head_bucket(Bucket=EXPECTED_BUCKET_NAME)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            message = exc.response.get("Error", {}).get("Message", "bucket not found")
            if code in ("404", "NoSuchBucket", "NotFound"):
                info["errors"].append(f"Bucket {EXPECTED_BUCKET_NAME} not found.")
            else:
                info["errors"].append(message)
            return info

        info["exists"] = True
        info["region"] = self._get_bucket_location(client, EXPECTED_BUCKET_NAME)
        info["region_matches"] = info["region"] == EXPECTED_REGION
        info["tags"] = self._get_bucket_tags(client, EXPECTED_BUCKET_NAME)
        info["tag_score"] = compute_best_practice_tag_score(
            info["tags"], cap=self.scoring_weights.components["best_practice_tags"].weight
        )
        public_access = self._get_public_access_block(client, EXPECTED_BUCKET_NAME)
        info["public_access_block"] = public_access.get("configuration", {})
        info["public_block_enabled"] = public_access.get("all_true", False)
        info["default_encryption_enabled"] = self._bucket_has_default_encryption(client, EXPECTED_BUCKET_NAME)
        info["lifecycle_rules"] = self._get_lifecycle_rules(client, EXPECTED_BUCKET_NAME)
        info["retention_days"] = self._extract_retention_days(info["lifecycle_rules"])
        if info["retention_days"] is not None:
            info["retention_ok"] = RETENTION_MIN_DAYS <= info["retention_days"] <= RETENTION_MAX_DAYS

        return info

    def _collect_errors(self, info: Dict[str, Any]) -> List[str]:
        """Build the list of blocking errors."""
        errors = list(info.get("errors", []))
        if not info.get("exists"):
            return errors or [f"Bucket {EXPECTED_BUCKET_NAME} not found."]
        if not info.get("region_matches"):
            errors.append(f"Bucket must be in {EXPECTED_REGION} (found {info.get('region')}).")
        if not info.get("retention_ok"):
            days = info.get("retention_days")
            if days is None:
                errors.append("Lifecycle policy to delete objects after ~6 months is missing.")
            else:
                errors.append(f"Lifecycle expiration set to {days} days; expected ~180.")
        return errors

    def _compute_components(self, info: Dict[str, Any]) -> Dict[str, ScoringComponentResult]:
        """Score each component based on collected info."""
        components: Dict[str, ScoringComponentResult] = {}
        for name, component in self.scoring_weights.components.items():
            if name == "exists_and_region":
                value = component.weight if (info.get("exists") and info.get("region_matches")) else 0.0
            elif name == "retention_policy":
                value = component.weight if info.get("retention_ok") else 0.0
            elif name == "block_public_access":
                value = component.weight if info.get("public_block_enabled") else 0.0
            elif name == "default_encryption":
                value = component.weight if info.get("default_encryption_enabled") else 0.0
            elif name == "best_practice_tags":
                value = min(info.get("tag_score", 0.0), component.weight)
            else:
                value = 0.0

            components[name] = ScoringComponentResult(
                label=component.label,
                description=component.description,
                value=round(value, 3),
                max=component.weight,
            )
        return components


def run_verifier(config: Dict[str, Any]) -> Dict[str, Any]:
    """Entry point for in-process verification."""
    endpoint = config.get("localstack_endpoint")
    scenario_path = config.get("scenario_path")
    verifier = S3ApplicationLogsVerifier(endpoint, Path(scenario_path) if scenario_path else None)
    result = verifier.run()
    return result.model_dump()
