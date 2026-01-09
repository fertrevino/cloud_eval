"""Registry of available verifier classes keyed by task_id."""
from __future__ import annotations

from typing import Dict, Type

from .verifier import Verifier
from tasks.aws.s3.simple_bucket.verify import S3BucketVerifier
from tasks.aws.s3.application_logs.verify import S3ApplicationLogsVerifier
from tasks.aws.s3.backups_bucket.verify import S3BackupsBucketVerifier
from tasks.aws.s3.set_bucket_private.verify import S3SetBucketPrivateVerifier
from tasks.aws.sqs.create_queue.verify import SQSQueueVerifier
from tasks.aws.sns.create_topic.verify import SNSTopicVerifier

# Map of task_id to verifier implementation
VERIFIERS: Dict[str, Type[Verifier]] = {
    "cloud-eval-s3-simple-bucket": S3BucketVerifier,
    "cloud-eval-s3-application-logs": S3ApplicationLogsVerifier,
    "cloud-eval-s3-backups-bucket": S3BackupsBucketVerifier,
    "cloud-eval-s3-set-bucket-private": S3SetBucketPrivateVerifier,
    "aws-sqs-create-queue": SQSQueueVerifier,
    "aws-sns-create-topic": SNSTopicVerifier,
}
