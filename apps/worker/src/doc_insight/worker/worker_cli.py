"""Process lifetime, signals and configured clients for `di worker run`."""

import argparse
import logging
import os
import signal
import socket
from contextlib import ExitStack
from threading import Event
from types import FrameType

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from doc_insight.observability import configure
from doc_insight.worker.embedder import FastEmbedEmbedder
from doc_insight.worker.object_store import S3ObjectStore
from doc_insight.worker.pipeline import Pipeline
from doc_insight.worker.processing import DocumentProcessor
from doc_insight.worker.providers import (
    HfTokenizer,
    LinguaLanguageDetector,
    SpacyNerExtractor,
)
from doc_insight.worker.repository import PostgresRepository
from doc_insight.worker.service import TRANSIENT, Worker
from doc_insight.worker.settings import Settings, get_settings
from doc_insight.worker.streams import RedisStreamConsumer
from pydantic import ValidationError
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


def add_commands(
    commands: "argparse._SubParsersAction[argparse.ArgumentParser]",
) -> None:
    worker = commands.add_parser("worker", help="Consume uploaded documents")
    worker.add_subparsers(dest="worker_command", required=True).add_parser("run")


def build_worker(settings: Settings, stack: ExitStack) -> Worker:
    client = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=settings.worker_block_ms / 1000 + 5,
    )
    stack.callback(client.close)
    engine = create_engine(
        settings.database_url,
        hide_parameters=True,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 3},
    )
    stack.callback(engine.dispose)
    objects = build_objects(settings, stack)
    pipeline = Pipeline(
        settings,
        LinguaLanguageDetector(settings),
        SpacyNerExtractor(settings),
        HfTokenizer(settings),
        FastEmbedEmbedder(settings),
    )
    processor = DocumentProcessor(PostgresRepository(engine), objects, pipeline)
    return Worker(
        RedisStreamConsumer(client, settings.worker_heartbeat_seconds),
        processor,
        settings,
        f"{socket.gethostname()}-{os.getpid()}",
    )


def build_objects(settings: Settings, stack: ExitStack) -> S3ObjectStore:
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key.get_secret_value(),
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        use_ssl=settings.s3_use_ssl,
        config=Config(connect_timeout=5, read_timeout=30, retries={"max_attempts": 2}),
    )
    stack.callback(s3.close)
    return S3ObjectStore(s3, settings.s3_bucket)


def install_signals(stopping: Event, stack: ExitStack) -> None:
    def stop(signum: int, frame: FrameType | None) -> None:
        if stopping.is_set():
            os._exit(0)
        stopping.set()

    for signum in (signal.SIGTERM, signal.SIGINT):
        previous = signal.signal(signum, stop)
        stack.callback(signal.signal, signum, previous)


def serve(settings: Settings) -> None:
    stopping = Event()
    with ExitStack() as signals:
        install_signals(stopping, signals)
        while not stopping.is_set():
            try:
                with ExitStack() as clients:
                    worker = build_worker(settings, clients)
                    worker.stopping = stopping
                    worker.run()
                return
            except TRANSIENT as error:
                logger.warning(
                    "status=unavailable error_class=%s", type(error).__name__
                )
                stopping.wait(min(settings.worker_reclaim_seconds, 5))


def run(parser: argparse.ArgumentParser) -> None:
    try:
        settings = get_settings()
        logging.basicConfig(level=logging.INFO)
        configure("worker")
        serve(settings)
    except ValidationError:
        parser.error("Invalid worker settings")
    except (
        SQLAlchemyError,
        BotoCoreError,
        ClientError,
        RedisError,
        ValueError,
        OSError,
    ) as error:
        parser.error(f"Worker startup failed ({type(error).__name__})")
