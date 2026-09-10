"""Serve HTTP or publish one tenant's outbox until shutdown."""

import argparse
import re
import signal
from threading import Event

import uvicorn
from botocore.exceptions import BotoCoreError, ClientError
from doc_insight.ingest.adapters import RedisPublisher
from doc_insight.ingest.relay import OutboxRelay
from doc_insight.ingest.settings import get_settings
from doc_insight.observability import configure
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError


def relay(tenant: str) -> None:
    settings = get_settings()
    configure("ingest-relay")
    stop = Event()
    previous = {
        sig: signal.signal(sig, lambda *_: stop.set())
        for sig in (signal.SIGTERM, signal.SIGINT)
    }
    engine = create_engine(settings.database_url, hide_parameters=True)
    client = Redis.from_url(
        settings.redis_url, socket_connect_timeout=5, socket_timeout=5
    )
    try:
        OutboxRelay(engine, RedisPublisher(client)).run(
            tenant,
            settings.relay_batch,
            settings.relay_poll_seconds,
            stop,
        )
    finally:
        client.close()
        engine.dispose()
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def main() -> None:
    parser = argparse.ArgumentParser(prog="di-ingest")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve")
    commands.add_parser("relay").add_argument("--tenant", required=True)
    args = parser.parse_args()
    if args.command == "relay" and not all(
        re.fullmatch(r"[A-Za-z0-9._-]{1,64}", tenant)
        for tenant in args.tenant.split(",")
    ):
        parser.error("Invalid tenant")
    try:
        settings = get_settings()
        if args.command == "serve":
            uvicorn.run(
                "doc_insight.ingest.main:app",
                host=settings.http_host,
                port=settings.http_port,
                access_log=False,
                log_level="critical",
            )
        else:
            relay(args.tenant)
    except (
        BotoCoreError,
        ClientError,
        RedisError,
        SQLAlchemyError,
        ValueError,
        OSError,
    ) as error:
        parser.exit(1, f"Ingest command failed ({type(error).__name__})\n")
