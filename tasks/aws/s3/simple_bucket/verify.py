"""S3 bucket creation and security verification."""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from cloud_eval.tools import compute_best_practice_tag_score
from cloud_eval.verifier import Verifier, VerificationResult, ScoringWeights, ScoringComponent, ScoringComponentResult

logger = logging.getLogger("cloud_eval.verify.s3")

UUID_SUFFIX_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
ULID_SUFFIX_RE = re.compile(r"[0-9A-HJKMNP-TV-Z]{26}$", re.IGNORECASE)
PUBLIC_ACCESS_BLOCK_KEYS = (
    "BlockPublicAcls",
    "IgnorePublicAcls",
    "BlockPublicPolicy",
    "RestrictPublicBuckets",
)
DEFAULT_ENCRYPTION_ALGORITHMS = {"AES256", "aws:kms"}


class S3BucketVerifier(Verifier):
    """Verifier for S3 bucket creation and security task."""

    scoring_weights = ScoringWeights(
        components={
            "base": ScoringComponent(
                name="base",
                label="Resource correctness",
                weight=0.65,
                description="Bucket exists in correct region (us-east-1)",
            ),
            "unique_name_or_runid": ScoringComponent(
                name="unique_name_or_runid",
                label="Unique name",
                weight=0.1,
                description="Bucket has unique suffix (UUID/ULID/random)",
            ),
            "block_public_access": ScoringComponent(
                name="block_public_access",
                label="Public access block",
                weight=0.1,
                description="PublicAccessBlock enabled",
            ),
            "default_encryption": ScoringComponent(
                name="default_encryption",
                label="Default encryption",
                weight=0.1,
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
        bucket_attributes = self._collect_bucket_attributes(client)
        score, component_breakdown, errors = self._calculate_score(bucket_attributes)
        
        return VerificationResult(
            score=round(score, 3),
            components=component_breakdown,
            passed=len(errors) == 0,
            errors=errors,
        )

    def _build_client(self):
        """Build boto3 S3 client."""
        return boto3.client(
            "s3",
            endpoint_url=self.endpoint,
            region_name="us-east-1",
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "test"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
        )

    def _get_bucket_location(self, client, bucket: str) -> str | None:
        """Get bucket region."""
        try:
            response = client.get_bucket_location(Bucket=bucket)
            region = response.get("LocationConstraint")
            if not region:
                return "us-east-1"
            return region
        except ClientError as exc:
            logger.debug("Could not determine bucket %s location: %s", bucket, exc)
            return None

    def _get_bucket_tags(self, client, bucket: str) -> list[dict[str, str]]:
        """Get bucket tags."""
        try:
            return client.get_bucket_tagging(Bucket=bucket).get("TagSet", [])
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code == "NoSuchTagSet":
                return []
            raise

    def _bucket_has_unique_suffix(self, bucket_name: str) -> bool:
        """Check if bucket name has unique suffix."""
        if not bucket_name:
            return False
        normalized = bucket_name.lower()
        if UUID_SUFFIX_RE.search(normalized):
            return True
        if ULID_SUFFIX_RE.search(bucket_name.upper()):
            return True
        suffix = bucket_name.split("-")[-1]
        if len(suffix) >= 8 and suffix.isalnum():
            digits = sum(char.isdigit() for char in suffix)
            letters = sum(char.isalpha() for char in suffix)
            if digits >= 4 and letters >= 2:
                return True
        return False

    def _get_public_access_block(self, client, bucket: str) -> dict[str, object]:
        """Get public access block configuration."""
        try:
            response = client.get_public_access_block(Bucket=bucket)
            configuration = response["PublicAccessBlockConfiguration"]
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

    def _list_bucket_names(self, client) -> list[str]:
        """List all bucket names."""
        try:
            response = client.list_buckets()
            return [bucket["Name"] for bucket in response.get("Buckets", []) if bucket.get("Name")]
        except ClientError as exc:
            logger.debug("Failed to list buckets: %s", exc)
            return []

    def _collect_bucket_attributes_for_bucket(self, client, bucket: str) -> dict[str, object]:
        """Collect evaluation attributes for a bucket."""
        bucket_attributes: dict[str, object] = {
            "bucket_exists": False,
            "region": None,
            "tags": [],
            "tag_score": 0.0,
            "unique_suffix": False,
            "public_access_block": {},
            "block_public_access_enabled": False,
            "default_encryption_enabled": False,
        }
        try:
            client.head_bucket(Bucket=bucket)
        except ClientError:
            return bucket_attributes

        bucket_attributes["bucket_exists"] = True
        bucket_attributes["region"] = self._get_bucket_location(client, bucket)
        tags = self._get_bucket_tags(client, bucket)
        bucket_attributes["tags"] = tags
        tag_dict = {tag.get("Key", ""): tag.get("Value", "") for tag in tags if tag.get("Key")}
        bucket_attributes["tag_score"] = compute_best_practice_tag_score(
            tag_dict, cap=self.scoring_weights.components["best_practice_tags"].weight
        )
        bucket_attributes["unique_suffix"] = self._bucket_has_unique_suffix(bucket)
        public_access = self._get_public_access_block(client, bucket)
        bucket_attributes["public_access_block"] = public_access.get("configuration", {})
        bucket_attributes["block_public_access_enabled"] = public_access.get("all_true", False)
        bucket_attributes["default_encryption_enabled"] = self._bucket_has_default_encryption(client, bucket)
        return bucket_attributes

    def _collect_bucket_attributes(self, client) -> dict[str, dict]:
        """Collect evaluation attributes for all buckets."""
        bucket_names = self._list_bucket_names(client)
        return {
            name: self._collect_bucket_attributes_for_bucket(client, name) 
            for name in bucket_names
        }

    def _calculate_score(
        self, bucket_attributes_map: dict[str, dict]
    ) -> tuple[float, dict[str, ScoringComponentResult], list[str]]:
        """Calculate verification score and validate bucket requirements.
        
        Returns:
            (score, components, errors)
        """
        errors: list[str] = []
        
        if not bucket_attributes_map:
            errors.append("No buckets exist in the environment.")
            return 0.0, {}, errors
        
        east_buckets = [
            name for name, sec in bucket_attributes_map.items() if sec.get("region") == "us-east-1"
        ]
        if not east_buckets:
            errors.append("Buckets exist but none are located in us-east-1.")
            return 0.0, {}, errors

        bucket_results: dict[str, dict[str, object]] = {}
        bucket_scores: list[float] = []
        component_totals = {name: 0.0 for name in self.scoring_weights.components}
        
        for bucket_name, security in bucket_attributes_map.items():
            region = security.get("region")
            base_score = self.scoring_weights.components["base"].weight if region == "us-east-1" else 0.0
            unique_bonus = self.scoring_weights.components["unique_name_or_runid"].weight if security.get("unique_suffix") else 0.0
            block_bonus = self.scoring_weights.components["block_public_access"].weight if security.get("block_public_access_enabled") else 0.0
            encryption_bonus = self.scoring_weights.components["default_encryption"].weight if security.get("default_encryption_enabled") else 0.0
            tag_bonus = min(security.get("tag_score", 0.0), self.scoring_weights.components["best_practice_tags"].weight)
            
            bucket_score = min(1.0, base_score + unique_bonus + block_bonus + encryption_bonus + tag_bonus)
            bucket_scores.append(bucket_score)
            bucket_results[bucket_name] = {
                "score": bucket_score,
                "components": {
                    "base": base_score,
                    "unique_name_or_runid": unique_bonus,
                    "block_public_access": block_bonus,
                    "default_encryption": encryption_bonus,
                    "best_practice_tags": tag_bonus,
                },
                "details": {
                    "region": region,
                    "unique_suffix": security.get("unique_suffix"),
                    "public_access_block": security.get("public_access_block"),
                    "default_encryption_enabled": security.get("default_encryption_enabled"),
                },
            }
            component_totals["base"] += bucket_results[bucket_name]["components"]["base"]
            component_totals["unique_name_or_runid"] += bucket_results[bucket_name]["components"]["unique_name_or_runid"]
            component_totals["block_public_access"] += bucket_results[bucket_name]["components"]["block_public_access"]
            component_totals["default_encryption"] += bucket_results[bucket_name]["components"]["default_encryption"]
            component_totals["best_practice_tags"] += bucket_results[bucket_name]["components"]["best_practice_tags"]

        final_score = sum(bucket_scores) / len(bucket_scores)
        bucket_count = len(bucket_scores)
        component_details: dict[str, ScoringComponentResult] = {}
        
        for name, component in self.scoring_weights.components.items():
            average = component_totals[name] / bucket_count
            component_details[name] = ScoringComponentResult(
                label=component.label,
                description=component.description,
                value=round(average, 3),
                max=component.weight,
            )
        
        return final_score, component_details, errors


if __name__ == "__main__":
    # Support old CLI interface for compatibility during transition
    import argparse

    parser = argparse.ArgumentParser(description="Verify S3 bucket creation")
    parser.add_argument(
        "--scenario-path",
        type=Path,
        default=Path(__file__).parent / "meta.json",
        help="Path to the scenario metadata file for this task.",
    )
    parser.add_argument(
        "--localstack-endpoint",
        required=True,
        help="LocalStack endpoint URL.",
    )
    parser.add_argument(
        "--write-report",
        type=Path,
        help="Write the verification summary as JSON to this path after the run.",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=0,
        help="Number of steps (aws_cli actions) taken during the run.",
    )
    parser.add_argument(
        "--skip-apply",
        action="store_true",
        help="Accepts the flag so that the runner can skip apply but still run verification.",
    )
    args = parser.parse_args()

    verifier = S3BucketVerifier(args.localstack_endpoint, args.scenario_path)
    result = verifier.verify()
    
    if args.write_report:
        args.write_report.write_text(result.model_dump_json(indent=2))
    else:
        print(result.model_dump_json(indent=2))

