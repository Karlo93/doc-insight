"""Long-lived S3 and Redis clients at the service boundary."""

import boto3
from botocore.config import Config
from doc_insight.contracts.ingest import DocumentUploaded
from doc_insight.ingest.settings import Settings
from doc_insight.worker.object_store import S3ObjectStore as BaseS3ObjectStore
from redis import Redis


class S3ObjectStore(BaseS3ObjectStore):
    @classmethod
    def from_settings(cls, settings: Settings) -> "S3ObjectStore":
        client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key.get_secret_value(),
            aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
            use_ssl=settings.s3_use_ssl,
            config=Config(
                connect_timeout=5, read_timeout=30, retries={"max_attempts": 2}
            ),
        )
        return cls(client, settings.s3_bucket)


class RedisPublisher:
    def __init__(self, client: Redis) -> None:
        self.client = client

    def publish(self, event: DocumentUploaded) -> None:
        self.client.xadd(
            "di:documents", {k: v for k, v in event.stream_fields().items()}
        )
