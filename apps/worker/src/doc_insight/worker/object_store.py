"""Shared S3 object adapter; each service owns configuration and client lifetime."""

from typing import BinaryIO, cast

from botocore.exceptions import ClientError
from mypy_boto3_s3 import S3Client


class S3ObjectStore:
    def __init__(self, client: S3Client, bucket: str) -> None:
        self.client, self.bucket = client, bucket

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
