"""S3 backups bucket verification."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

import boto3
from botocore.exceptions import ClientError

from cloud_eval.verifier import (
    Verifier,
    VerificationResult,
    ScoringWeights,
    ScoringComponent,
    ScoringComponentResult,
)

logger = logging.getLogger("cloud_eval.verify.s3.backups")

GLACIER_STORAGE_CLASSES = {"GLACIER", "DEEP_ARCHIVE", "GLACIER_IR"}
DEFAULT_ENCRYPTION_ALGORITHMS = {"AES256", "aws:kms"}


class S3BackupsBucketVerifier(Verifier):
    """Verifier for backups bucket: existence, versioning, lifecycle to Glacier, encryption, and safety."""

    scoring_weights = ScoringWeights(
        components={
            "exists": ScoringComponent(
                name="exists",
                label="Bucket exists",
                weight=0.5,
                description="At least one S3 bucket is present for backups",
            ),
            "versioning": ScoringComponent(
                name="versioning",
                label="Versioning enabled",
                weight=0.2,
                description="Versioning protects against overwrites/deletes",
            ),
            "lifecycle_glacier": ScoringComponent(
                name="lifecycle_glacier",
                label="Lifecycle to Glacier",
                weight=0.2,
                description="Lifecycle rule transitions data to Glacier storage classes",
            ),
            "encryption": ScoringComponent(
                name="encryption",
                label="Default encryption",
                weight=0.1,
                description="Server-side encryption configured",
            ),
        }
    )

    def __init__(self, localstack_endpoint: str, scenario_path: Path | None = None):
        """Initialize verifier."""
        super().__init__(localstack_endpoint)
        self.scenario_path = scenario_path

    def verify(self) -> VerificationResult:
        """Run verification and return structured result."""
        client = self._build_client()
        bucket_map = self._collect_bucket_attributes(client)
        errors: List[str] = []

        if not bucket_map:
            errors.append("No buckets found for backups.")
            return VerificationResult(
                score=0.0,
                components={},
                passed=False,
                errors=errors,
            )

        best_name, best = self._choose_best_bucket(bucket_map)

        if best.get("delete_actions"):
            errors.append(f"Bucket {best_name} has lifecycle delete/expiration actions; backups should not delete data.")

        components = self._compute_components(best)
        total_score = sum(comp.value for comp in components.values())

        return VerificationResult(
            score=round(total_score, 3),
            components=components,
            passed=len(errors) == 0,
            errors=errors,
        )

    def _build_client(self):
        """Build boto3 S3 client."""
        region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
        return boto3.client(
            "s3",
            endpoint_url=self.endpoint,
            region_name=region,
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "test"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
        )

    def _list_bucket_names(self, client) -> List[str]:
        """List all bucket names."""
        try:
            response = client.list_buckets()
            return [bucket["Name"] for bucket in response.get("Buckets", []) if bucket.get("Name")]
        except ClientError as exc:
            logger.debug("Failed to list buckets: %s", exc)
            return []

    def _bucket_exists(self, client, bucket: str) -> bool:
        """Check if bucket exists via head_bucket."""
        try:
            client.head_bucket(Bucket=bucket)
            return True
        except ClientError as exc:
            logger.debug("Bucket %s head failed: %s", bucket, exc)
            return False

    def _versioning_enabled(self, client, bucket: str) -> bool:
        """Check if versioning is enabled."""
        try:
            resp = client.get_bucket_versioning(Bucket=bucket)
            return resp.get("Status") == "Enabled"
        except ClientError as exc:
            logger.debug("Versioning check failed for %s: %s", bucket, exc)
            return False

    def _get_lifecycle_rules(self, client, bucket: str) -> List[Dict[str, Any]]:
        """Fetch lifecycle rules if configured."""
        try:
            response = client.get_bucket_lifecycle_configuration(Bucket=bucket)
            return response.get("Rules", [])
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in ("NoSuchLifecycleConfiguration", "NoSuchLifecycleConfigurationFault"):
                return []
            logger.debug("Lifecycle check failed for %s: %s", bucket, exc)
            return []

    def _has_glacier_transition(self, rules: List[Dict[str, Any]]) -> bool:
        """Determine if any lifecycle transition targets a Glacier class."""
        for rule in rules:
            transitions = rule.get("Transitions") or []
            for transition in transitions:
                storage_class = str(transition.get("StorageClass", "")).upper()
                if storage_class in GLACIER_STORAGE_CLASSES:
                    return True
        return False

    def _has_delete_actions(self, rules: List[Dict[str, Any]]) -> bool:
        """Detect lifecycle rules that delete/expire objects."""
        for rule in rules:
            expiration = rule.get("Expiration") or {}
            if expiration.get("Days") or expiration.get("Date") or expiration.get("ExpiredObjectDeleteMarker"):
                return True
            noncurrent = rule.get("NoncurrentVersionExpiration") or {}
            if noncurrent.get("NoncurrentDays"):
                return True
        return False

    def _default_encryption_enabled(self, client, bucket: str) -> bool:
        """Check if bucket default encryption is configured."""
        try:
            response = client.get_bucket_encryption(Bucket=bucket)
            rules = response.get("ServerSideEncryptionConfiguration", {}).get("Rules", [])
            for rule in rules:
                algorithm = rule.get("ApplyServerSideEncryptionByDefault", {}).get("SSEAlgorithm")
                if algorithm in DEFAULT_ENCRYPTION_ALGORITHMS:
                    return True
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in (
                "ServerSideEncryptionConfigurationNotFoundError",
                "EncryptionConfigurationNotFoundError",
            ):
                return False
            logger.debug("Encryption check failed for %s: %s", bucket, exc)
        return False

    def _collect_bucket_attributes(self, client) -> Dict[str, Dict[str, Any]]:
        """Collect evaluation attributes for all buckets."""
        bucket_names = self._list_bucket_names(client)
        attributes: Dict[str, Dict[str, Any]] = {}
        for name in bucket_names:
            if not self._bucket_exists(client, name):
                continue

            lifecycle_rules = self._get_lifecycle_rules(client, name)
            has_glacier = self._has_glacier_transition(lifecycle_rules)
            has_delete = self._has_delete_actions(lifecycle_rules)
            versioning = self._versioning_enabled(client, name)
            encryption = self._default_encryption_enabled(client, name)

            base_score = self.scoring_weights.components["exists"].weight
            version_score = self.scoring_weights.components["versioning"].weight if versioning else 0.0
            lifecycle_score = self.scoring_weights.components["lifecycle_glacier"].weight if has_glacier else 0.0
            encryption_score = self.scoring_weights.components["encryption"].weight if encryption else 0.0

            total_score = base_score + version_score + lifecycle_score + encryption_score

            attributes[name] = {
                "versioning": versioning,
                "has_glacier": has_glacier,
                "delete_actions": has_delete,
                "encryption": encryption,
                "score": total_score,
            }
        return attributes

    def _choose_best_bucket(self, attributes: Dict[str, Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
        """Pick the highest-scoring bucket, preferring those without delete actions."""
        safe = {name: info for name, info in attributes.items() if not info.get("delete_actions")}
        candidates = safe if safe else attributes
        best_name = max(candidates, key=lambda k: candidates[k].get("score", 0.0))
        return best_name, candidates[best_name]

    def _compute_components(self, info: Dict[str, Any]) -> Dict[str, ScoringComponentResult]:
        """Score each component based on bucket info."""
        components: Dict[str, ScoringComponentResult] = {}
        for name, component in self.scoring_weights.components.items():
            if name == "exists":
                value = component.weight
            elif name == "versioning":
                value = component.weight if info.get("versioning") else 0.0
            elif name == "lifecycle_glacier":
                value = component.weight if info.get("has_glacier") else 0.0
            elif name == "encryption":
                value = component.weight if info.get("encryption") else 0.0
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
    verifier = S3BackupsBucketVerifier(endpoint, Path(scenario_path) if scenario_path else None)
    result = verifier.run()
    return result.model_dump()
