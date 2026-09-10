import os
import socket
from threading import local

import psycopg
import pytest
from doc_insight.query.settings import get_settings as query_settings
from doc_insight.worker.settings import get_settings


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest):
    # Local tuning must not change assertions; keep machine-specific binary/cache paths.
    for key in list(os.environ):
        if request.node.get_closest_marker("integration") and (
            key == "DI_REDIS_URL" or key.startswith("DI_S3_")
        ):
            continue
        if key == "DI_LLM_API_KEY" and request.node.get_closest_marker("external"):
            continue
        if key.startswith("DI_") and key not in {
            "DI_TESSERACT_CMD",
            "DI_MODEL_CACHE",
            "DI_DATABASE_URL",
            "DI_MIGRATION_DATABASE_URL",
            "DI_ALLOW_REMOTE_TEST_DB",
        }:
            monkeypatch.delenv(key)
    query_settings.cache_clear()
    get_settings.cache_clear()
    yield
    query_settings.cache_clear()
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def offline_by_default(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    if any(
        request.node.get_closest_marker(mark)
        for mark in ("models", "integration", "external")
    ):
        return

    def blocked(*args, **kwargs):
        raise AssertionError("Network access is forbidden in the default test suite")

    original_connect, original_pair = socket.socket.connect, socket.socketpair
    internal = local()

    def guarded_connect(sock, address):
        # Windows implements asyncio's self-pipe with a loopback socketpair.
        if getattr(internal, "socketpair", False) and address[0] in {
            "127.0.0.1",
            "::1",
        }:
            return original_connect(sock, address)
        return blocked(sock, address)

    def socketpair(*args, **kwargs):
        internal.socketpair = True
        try:
            return original_pair(*args, **kwargs)
        finally:
            internal.socketpair = False

    monkeypatch.setattr(socket, "socketpair", socketpair)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    # libpq can open sockets in C, bypassing Python's socket guard.
    monkeypatch.setattr(psycopg, "connect", blocked)
