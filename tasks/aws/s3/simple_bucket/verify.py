from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

from botocore.exceptions import ClientError
from cloud_eval.logging_config import configure_logging
from cloud_eval.scenario import load_scenario
from cloud_eval.tools import compute_best_practice_tag_score

configure_logging()
logger = logging.getLogger("cloud_eval.verify")

UUID_SUFFIX_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
ULID_SUFFIX_RE = re.compile(r"[0-9A-HJKMNP-TV-Z]{26}$", re.IGNORECASE)
PUBLIC_ACCESS_BLOCK_KEYS = (
    "BlockPublicAcls",
    "IgnorePublicAcls",
    "BlockPublicPolicy",
    "RestrictPublicBuckets",
)
DEFAULT_ENCRYPTION_ALGORITHMS = {"AES256", "aws:kms"}
COMPONENT_META = {
    "base": {"max": 0.65, "label": "Resource correctness"},
    "unique_name_or_runid": {"max": 0.1, "label": "Unique name"},
    "block_public_access": {"max": 0.1, "label": "Public access block"},
    "default_encryption": {"max": 0.1, "label": "Default encryption"},
    "best_practice_tags": {"max": 0.05, "label": "Tags applied"},
}
TAGS_WEIGHT = COMPONENT_META["best_practice_tags"]["max"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run and verify the private S3 bucket task.")
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
    return parser.parse_args()


def _get_bucket_location(client, bucket: str) -> str | None:
    try:
        response = client.get_bucket_location(Bucket=bucket)
        region = response.get("LocationConstraint")
        if not region:
            return "us-east-1"
        return region
    except ClientError as exc:
        logger.debug("Could not determine bucket %s location: %s", bucket, exc)
        return None


def _get_bucket_tags(client, bucket: str) -> list[dict[str, str]]:
    try:
        return client.get_bucket_tagging(Bucket=bucket).get("TagSet", [])
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code == "NoSuchTagSet":
            return []
        raise


def _bucket_has_unique_suffix(bucket_name: str) -> bool:
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


def _get_public_access_block(client, bucket: str) -> dict[str, object]:
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


def _bucket_has_default_encryption(client, bucket: str) -> bool:
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


def _list_bucket_names(client) -> list[str]:
    try:
        response = client.list_buckets()
        return [bucket["Name"] for bucket in response.get("Buckets", []) if bucket.get("Name")]
    except ClientError as exc:
        logger.debug("Failed to list buckets: %s", exc)
        return []


def _collect_bucket_security(client, bucket: str) -> dict[str, object]:
    bucket_security: dict[str, object] = {
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
        return bucket_security

    bucket_security["bucket_exists"] = True
    bucket_security["region"] = _get_bucket_location(client, bucket)
    tags = _get_bucket_tags(client, bucket)
    bucket_security["tags"] = tags
    tag_dict = {tag.get("Key", ""): tag.get("Value", "") for tag in tags if tag.get("Key")}
    bucket_security["tag_score"] = compute_best_practice_tag_score(tag_dict, cap=TAGS_WEIGHT)
    bucket_security["unique_suffix"] = _bucket_has_unique_suffix(bucket)
    public_access = _get_public_access_block(client, bucket)
    bucket_security["public_access_block"] = public_access.get("configuration", {})
    bucket_security["block_public_access_enabled"] = public_access.get("all_true", False)
    bucket_security["default_encryption_enabled"] = _bucket_has_default_encryption(client, bucket)
    return bucket_security


def _verify_tasks(client, scenario) -> tuple[list[str], dict[str, dict]]:
    failures: list[str] = []
    bucket_names = _list_bucket_names(client)
    bucket_security_map = {
        name: _collect_bucket_security(client, name) for name in bucket_names
    }

    if not bucket_security_map:
        failures.append("No buckets exist in the environment.")
    else:
        east_buckets = [
            name for name, sec in bucket_security_map.items() if sec.get("region") == "us-east-1"
        ]
        if not east_buckets:
            failures.append(
                "Buckets exist but none are located in us-east-1."
            )
    for bucket_name, bucket_security in bucket_security_map.items():
        logger.debug("Verification results for %s: %s", bucket_name, bucket_security)

    return failures, bucket_security_map


def _calculate_score(
    failures: list[str], bucket_security_map: dict[str, dict]
) -> tuple[float, dict[str, object]]:
    if failures:
        return 0.0, {"reason": "bucket_failed", "failures": failures}
    if not bucket_security_map:
        return (
            0.0,
            {
                "reason": "no_buckets_defined",
                "message": "Scenario does not define any buckets to verify.",
            },
        )

    bucket_results: dict[str, dict[str, object]] = {}
    bucket_scores: list[float] = []
    component_totals = {name: 0.0 for name in COMPONENT_META}
    for bucket_name, security in bucket_security_map.items():
        region = security.get("region")
        base_score = COMPONENT_META["base"]["max"] if region == "us-east-1" else 0.0
        unique_bonus = COMPONENT_META["unique_name_or_runid"]["max"] if security.get("unique_suffix") else 0.0
        block_bonus = COMPONENT_META["block_public_access"]["max"] if security.get("block_public_access_enabled") else 0.0
        encryption_bonus = COMPONENT_META["default_encryption"]["max"] if security.get("default_encryption_enabled") else 0.0
        tag_bonus = min(security.get("tag_score", 0.0), COMPONENT_META["best_practice_tags"]["max"])
        bucket_score = min(
            1.0, base_score + unique_bonus + block_bonus + encryption_bonus + tag_bonus
        )
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
    component_details: dict[str, dict[str, object]] = {}
    for name, meta in COMPONENT_META.items():
        average = component_totals[name] / bucket_count
        component_details[name] = {
            "label": meta.get("label", name),
            "value": average,
            "max": meta.get("max"),
        }
    return (
        final_score,
        {
            "reason": "bucket_security_checks",
            "buckets": bucket_results,
            "score": final_score,
            "components": component_details,
        },
    )


def main() -> int:
    args = parse_args()

    scenario = load_scenario(args.scenario_path)

    import boto3

    session = boto3.Session(
        aws_access_key_id="test", aws_secret_access_key="test", region_name="us-east-1"
    )
    client = session.client("s3", endpoint_url=args.localstack_endpoint)

    failures, bucket_security = _verify_tasks(client, scenario)
    score, score_details = _calculate_score(failures, bucket_security)
    verification = {
        "bucket_security": bucket_security,
        "failures": failures,
        "task_id": scenario.metadata.task_id,
        "task_name": scenario.metadata.task_name,
        "steps": args.steps,
        "score": score,
        "score_details": score_details,
    }

    if args.write_report:
        args.write_report.write_text(json.dumps(verification))
        logger.info("Verification summary written to %s", args.write_report)

    if failures:
        print("Verification failed:")
        for failure in failures:
            print(f" - {failure}")
        return 1

    print("Task verified successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
