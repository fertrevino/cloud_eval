"""Setup script to provision a publicly accessible bucket for the privacy-fix task."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

BUCKET_NAME = "application-storage-873dafa5-ccef-4ab6-8b4b-454f34041350"
REGION = "us-east-1"

logger = logging.getLogger("cloud_eval.setup.s3.set_bucket_private")


def _build_client(endpoint: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=REGION,
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "test"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
    )


def _ensure_bucket_exists(client) -> None:
    try:
        client.head_bucket(Bucket=BUCKET_NAME)
        return
    except ClientError:
        pass

    create_kwargs = {"Bucket": BUCKET_NAME}
    if REGION != "us-east-1":
        create_kwargs["CreateBucketConfiguration"] = {"LocationConstraint": REGION}
    client.create_bucket(**create_kwargs)


def _make_bucket_public(client) -> None:
    # Disable public access block
    client.put_public_access_block(
        Bucket=BUCKET_NAME,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": False,
            "IgnorePublicAcls": False,
            "BlockPublicPolicy": False,
            "RestrictPublicBuckets": False,
        },
    )

    # Public-read ACL
    client.put_bucket_acl(Bucket=BUCKET_NAME, ACL="public-read")

    # Bucket policy allowing public reads
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowPublicRead",
                "Effect": "Allow",
                "Principal": "*",
                "Action": ["s3:GetObject"],
                "Resource": [f"arn:aws:s3:::{BUCKET_NAME}/*"],
            }
        ],
    }
    client.put_bucket_policy(Bucket=BUCKET_NAME, Policy=json.dumps(policy))


def run_setup(endpoint: str, scenario_path: Path | None = None) -> None:
    """Provision a non-private bucket to serve as the starting state for the task."""
    client = _build_client(endpoint)
    _ensure_bucket_exists(client)
    _make_bucket_public(client)
    logger.info("Setup complete: bucket %s is public/readable", BUCKET_NAME)
