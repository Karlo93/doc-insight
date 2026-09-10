import socket
from unittest.mock import Mock

import psycopg
import pytest
from doc_insight.query.main import create_app
from doc_insight.query.settings import Settings, get_settings
from fastapi.testclient import TestClient


def test_lifespan_owns_runtime_and_releases_clients(monkeypatch):
    runtime = Mock()
    factory = Mock(return_value=runtime)
    monkeypatch.setattr("doc_insight.query.main.Runtime", factory)
    with TestClient(create_app()) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/readyz").status_code == 200
        runtime.ready.assert_called_once()
        runtime.close.assert_not_called()
    runtime.close.assert_called_once()
    assert get_settings() is get_settings()


def test_cli_serve(monkeypatch):
    from doc_insight.query.cli import main

    run = Mock()
    monkeypatch.setattr("doc_insight.query.cli.uvicorn.run", run)
    monkeypatch.setattr("sys.argv", ["di-query", "serve"])
    main()
    run.assert_called_once_with(
        "doc_insight.query.main:app", host="127.0.0.1", port=8002
    )


def test_runtime_reuses_clients_and_retries_repository_initialization(monkeypatch):
    from doc_insight.query.runtime import Runtime

    engine, client, embedder, repository = Mock(), Mock(), Mock(), Mock()
    connection = Mock()
    from contextlib import nullcontext

    engine.connect.return_value = nullcontext(connection)
    monkeypatch.setattr(
        "doc_insight.query.runtime.create_engine", Mock(return_value=engine)
    )
    monkeypatch.setattr(
        "doc_insight.query.runtime.httpx.Client", Mock(return_value=client)
    )
    monkeypatch.setattr(
        "doc_insight.query.runtime.FastEmbedEmbedder", Mock(return_value=embedder)
    )
    factory = Mock(side_effect=[OSError("unavailable"), repository])
    monkeypatch.setattr("doc_insight.query.runtime.PostgresRepository", factory)
    runtime = Runtime(Settings(llm_api_key="test"))
    with pytest.raises(OSError):
        runtime.get_service()
    service = runtime.get_service()
    assert runtime.get_service() is service
    assert factory.call_count == 2
    runtime.ready()
    embedder.embed_query.assert_called_once_with("readiness")
    runtime.close()
    client.close.assert_called_once()
    engine.dispose.assert_called_once()


def test_socket_guard_still_blocks_network_and_libpq():
    with socket.socket() as sock, pytest.raises(AssertionError):
        sock.connect(("127.0.0.1", 55434))
    with pytest.raises(AssertionError):
        socket.getaddrinfo("example.invalid", 443)
    with pytest.raises(AssertionError):
        psycopg.connect("host=127.0.0.1")


@pytest.mark.models
def test_actual_token_limit_maps_to_400_before_database_access():
    from doc_insight.query.generation import FallbackGenerator
    from doc_insight.query.service import QueryService
    from doc_insight.worker.embedder import FastEmbedEmbedder

    settings = Settings(llm_api_key="")
    repository = Mock()
    service = QueryService(
        repository, FastEmbedEmbedder(settings), FallbackGenerator(), settings
    )
    with TestClient(create_app(service)) as client:
        response = client.post(
            "/query", headers={"X-Tenant-Id": "demo"}, json={"question": "hello " * 127}
        )
    assert response.status_code == 400 and "126 content token" in response.text
    repository.snapshot.assert_not_called()
