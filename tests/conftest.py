import os
import socket

import psycopg
import pytest
from doc_insight.worker.settings import get_settings


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch: pytest.MonkeyPatch):
    # Local tuning must not change assertions; keep machine-specific binary/cache paths.
    for key in list(os.environ):
        if key.startswith("DI_") and key not in {
            "DI_TESSERACT_CMD",
            "DI_MODEL_CACHE",
            "DI_DATABASE_URL",
            "DI_ALLOW_REMOTE_TEST_DB",
        }:
            monkeypatch.delenv(key)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def offline_by_default(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    if any(request.node.get_closest_marker(mark) for mark in ("models", "integration")):
        return

    def blocked(*args, **kwargs):
        raise AssertionError("Network access is forbidden in the default test suite")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    # libpq can open sockets in C, bypassing Python's socket guard.
    monkeypatch.setattr(psycopg, "connect", blocked)
