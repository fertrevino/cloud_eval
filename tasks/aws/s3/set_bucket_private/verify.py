"""S3 bucket privacy verification."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict

import boto3
from botocore.exceptions import ClientError

from cloud_eval.verifier import (
    Verifier,
    VerificationResult,
    ScoringWeights,
    ScoringComponent,
    ScoringComponentResult,
)

logger = logging.getLogger("cloud_eval.verify.s3.set_bucket_private")

BUCKET_NAME = "application-storage-873dafa5-ccef-4ab6-8b4b-454f34041350"
PUBLIC_ACCESS_BLOCK_KEYS = (
    "BlockPublicAcls",
    "IgnorePublicAcls",
    "BlockPublicPolicy",
    "RestrictPublicBuckets",
)


class S3SetBucketPrivateVerifier(Verifier):
    """Verifier to ensure the existing bucket is private."""

    scoring_weights = ScoringWeights(
        components={
            "block_public_access": ScoringComponent(
                name="block_public_access",
                label="Block public access",
                weight=0.4,
                description="Bucket PublicAccessBlock is fully enabled",
            ),
            "policy_not_public": ScoringComponent(
                name="policy_not_public",
                label="Policy not public",
                weight=0.35,
                description="Bucket policy status reports non-public",
            ),
            "no_public_acl": ScoringComponent(
                name="no_public_acl",
                label="No public ACL",
                weight=0.25,
                description="No AllUsers or AuthenticatedUsers ACL grants",
            ),
        }
    )

    def __init__(self, localstack_endpoint: str, scenario_path: Path | None = None):
        super().__init__(localstack_endpoint)
        self.scenario_path = scenario_path

    def verify(self) -> VerificationResult:
        client = self._build_client()
        info = self._collect_info(client)
        errors = self._collect_errors(info)
        components = self._compute_components(info)
        self._log_diagnostics(info, components)
        total_score = sum(comp.value for comp in components.values())
        return VerificationResult(
            score=round(total_score, 3),
            components=components,
            passed=len(errors) == 0,
            errors=errors,
        )

    def _build_client(self):
        region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
        return boto3.client(
            "s3",
            endpoint_url=self.endpoint,
            region_name=region,
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "test"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
        )

    def _bucket_exists(self, client) -> bool:
        try:
            client.head_bucket(Bucket=BUCKET_NAME)
            return True
        except ClientError as exc:
            logger.debug("Bucket head failed for %s: %s", BUCKET_NAME, exc)
            return False

    def _get_acl_public(self, client) -> bool:
        """Return True if ACL grants public (AllUsers/AuthenticatedUsers)."""
        try:
            acl = client.get_bucket_acl(Bucket=BUCKET_NAME)
            grants = acl.get("Grants", []) or []
            for grant in grants:
                grantee = grant.get("Grantee", {})
                if grantee.get("Type") == "Group":
                    uri = grantee.get("URI", "")
                    if "AllUsers" in uri or "AuthenticatedUsers" in uri:
                        return True
        except ClientError as exc:
            logger.debug("ACL check failed for %s: %s", BUCKET_NAME, exc)
        return False

    def _policy_status_public(self, client) -> bool:
        """Use policy status to determine if the bucket is public."""
        try:
            resp = client.get_bucket_policy_status(Bucket=BUCKET_NAME)
            status = resp.get("PolicyStatus", {}) or {}
            return bool(status.get("IsPublic"))
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in ("NoSuchBucketPolicy", "NoSuchPolicy", "NoSuchBucketPolicyStatus"):
                return False
            logger.debug("Policy status fetch failed for %s: %s", BUCKET_NAME, exc)
            raise

    def _get_policy(self, client) -> Dict[str, Any]:
        """Fetch bucket policy JSON if present."""
        try:
            resp = client.get_bucket_policy(Bucket=BUCKET_NAME)
            policy_str = resp.get("Policy", "{}")
            logger.debug("Fetched policy for %s: %s", BUCKET_NAME, policy_str)
            return json.loads(policy_str)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in ("NoSuchBucketPolicy", "NoSuchPolicy"):
                return {}
            logger.debug("Policy fetch failed for %s: %s", BUCKET_NAME, exc)
            return {}
        except json.JSONDecodeError:
            logger.debug("Policy JSON decode failed for %s", BUCKET_NAME)
            return {}

    def _policy_has_public_allow(self, policy: Dict[str, Any]) -> bool:
        """Detect public principals in bucket policy."""
        statements = policy.get("Statement") or []
        if isinstance(statements, dict):
            statements = [statements]
        for stmt in statements:
            if str(stmt.get("Effect", "")).lower() != "allow":
                continue
            principal = stmt.get("Principal")
            if principal == "*" or principal == {"AWS": "*"}:
                return True
            if isinstance(principal, dict):
                aws = principal.get("AWS")
                if aws == "*" or aws == ["*"]:
                    return True
        return False

    def _get_public_access_block(self, client) -> Dict[str, Any]:
        try:
            resp = client.get_public_access_block(Bucket=BUCKET_NAME)
            config = resp.get("PublicAccessBlockConfiguration", {})
            return {
                "configuration": config,
                "all_true": all(config.get(k) for k in PUBLIC_ACCESS_BLOCK_KEYS),
            }
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code == "NoSuchPublicAccessBlockConfiguration":
                return {"configuration": {}, "all_true": False}
            logger.debug("PublicAccessBlock fetch failed for %s: %s", BUCKET_NAME, exc)
            return {"configuration": {}, "all_true": False}

    def _collect_info(self, client) -> Dict[str, Any]:
        exists = self._bucket_exists(client)
        pab = self._get_public_access_block(client) if exists else {"configuration": {}, "all_true": False}
        acl_public = self._get_acl_public(client) if exists else False
        policy_status_public = False
        policy_status_supported = True
        policy_public_fallback = False
        if exists:
            try:
                policy_status_public = self._policy_status_public(client)
            except ClientError:
                policy_status_supported = False
                policy = self._get_policy(client)
                policy_public_fallback = self._policy_has_public_allow(policy)
        return {
            "exists": exists,
            "acl_public": acl_public,
            "policy_status_public": policy_status_public,
            "policy_status_supported": policy_status_supported,
            "policy_public_fallback": policy_public_fallback,
            "pab_all": pab.get("all_true", False),
        }

    def _collect_errors(self, info: Dict[str, Any]) -> list[str]:
        errors: list[str] = []
        if not info.get("exists"):
            errors.append(f"Bucket {BUCKET_NAME} not found.")
            return errors
        if not info.get("pab_all"):
            errors.append("PublicAccessBlock is not fully enabled.")
        if info.get("acl_public"):
            errors.append("Bucket ACL grants public access.")
        if info.get("policy_status_public") or info.get("policy_public_fallback"):
            errors.append("Bucket policy makes the bucket public.")
        return errors

    def _log_diagnostics(self, info: Dict[str, Any], components: Dict[str, ScoringComponentResult]) -> None:
        """Emit helpful logs to understand scoring outcomes."""
        summary = {
            "exists": info.get("exists"),
            "acl_public": info.get("acl_public"),
            "policy_status_public": info.get("policy_status_public"),
            "policy_status_supported": info.get("policy_status_supported"),
            "policy_public_fallback": info.get("policy_public_fallback"),
            "pab_all": info.get("pab_all"),
            "component_scores": {name: comp.value for name, comp in components.items()},
        }
        logger.info("set-bucket-private diagnostics: %s", json.dumps(summary))

    def _compute_components(self, info: Dict[str, Any]) -> Dict[str, ScoringComponentResult]:
        components: Dict[str, ScoringComponentResult] = {}
        for name, comp in self.scoring_weights.components.items():
            if name == "block_public_access":
                value = comp.weight if info.get("pab_all") else 0.0
            elif name == "policy_not_public":
                safe_policy = not info.get("policy_status_public") and not info.get("policy_public_fallback")
                value = comp.weight if info.get("exists") and safe_policy else 0.0
            elif name == "no_public_acl":
                value = comp.weight if (info.get("exists") and not info.get("acl_public")) else 0.0
            else:
                value = 0.0
            components[name] = ScoringComponentResult(
                label=comp.label,
                description=comp.description,
                value=round(value, 3),
                max=comp.weight,
            )
        return components


def run_verifier(config: Dict[str, Any]) -> Dict[str, Any]:
    endpoint = config.get("localstack_endpoint")
    scenario_path = config.get("scenario_path")
    verifier = S3SetBucketPrivateVerifier(endpoint, Path(scenario_path) if scenario_path else None)
    result = verifier.run()
    return result.model_dump()
