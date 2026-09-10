"""Process lifetime and readiness of reusable service clients."""

from collections.abc import Callable
from dataclasses import dataclass

from doc_insight.contracts.ingest import ObjectStore
from doc_insight.contracts.storage import DocumentRepository
from doc_insight.ingest.adapters import S3ObjectStore
from doc_insight.ingest.settings import Settings
from doc_insight.worker.repository import PostgresRepository
from redis import Redis
from sqlalchemy import create_engine, text


@dataclass
class Resources:
    repository: DocumentRepository
    objects: ObjectStore
    ready: Callable[[], None]
    close: Callable[[], None]


def create_resources(settings: Settings) -> Resources:
    engine = create_engine(settings.database_url, hide_parameters=True)
    objects = S3ObjectStore.from_settings(settings)
    redis = Redis.from_url(
        settings.redis_url, socket_connect_timeout=5, socket_timeout=5
    )

    def close() -> None:
        redis.close()
        objects.client.close()
        engine.dispose()

    def ready() -> None:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        objects.client.head_bucket(Bucket=settings.s3_bucket)
        redis.ping()

    try:
        return Resources(PostgresRepository(engine), objects, ready, close)
    except Exception:
        close()
        raise
