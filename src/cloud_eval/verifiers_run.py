"""Registry of available verifier classes keyed by task_id."""
from __future__ import annotations

from typing import Dict, Type

from .verifier import Verifier
from tasks.aws.s3.simple_bucket.verify import S3BucketVerifier
from tasks.aws.sqs.create_queue.verify import SQSQueueVerifier
from tasks.aws.sns.create_topic.verify import SNSTopicVerifier

# Map of task_id to verifier implementation
VERIFIERS: Dict[str, Type[Verifier]] = {
    "cloud-eval-s3-simple-bucket": S3BucketVerifier,
    "aws-sqs-create-queue": SQSQueueVerifier,
    "aws-sns-create-topic": SNSTopicVerifier,
}
