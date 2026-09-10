"""Long-lived S3 and Redis clients at the service boundary."""

from typing import BinaryIO, cast

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from doc_insight.contracts.ingest import DocumentUploaded
from doc_insight.ingest.settings import Settings
from mypy_boto3_s3 import S3Client
from redis import Redis


class S3ObjectStore:
    def __init__(self, client: S3Client, bucket: str) -> None:
        self.client, self.bucket = client, bucket

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

    def put(self, key: str, stream: BinaryIO, size: int, media_type: str) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=stream,
            ContentLength=size,
            ContentType=media_type,
            ServerSideEncryption="AES256",
        )

    def get(self, key: str) -> BinaryIO:
        return cast(
            BinaryIO, self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
        )

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as error:
            if error.response["Error"]["Code"] in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise
        return True


class RedisPublisher:
    def __init__(self, client: Redis) -> None:
        self.client = client

    def publish(self, event: DocumentUploaded) -> None:
        self.client.xadd(
            "di:documents", {k: v for k, v in event.stream_fields().items()}
        )
