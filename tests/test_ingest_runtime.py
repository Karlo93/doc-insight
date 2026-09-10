import signal
from io import BytesIO
from threading import Event
from unittest.mock import Mock
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError
from doc_insight.ingest import cli, runtime
from doc_insight.ingest.adapters import S3ObjectStore
from doc_insight.ingest.relay import OutboxRelay
from doc_insight.ingest.settings import Settings, get_settings
from doc_insight.testing.ingest import InMemoryObjectStore
from pydantic import ValidationError


def test_settings_require_credentials_and_validate_limits(monkeypatch):
    # Fail at startup when storage credentials or resource limits are invalid.
    get_settings.cache_clear()
    with pytest.raises(ValidationError):
        get_settings()
    monkeypatch.setenv("DI_S3_ACCESS_KEY", "local-test")
    monkeypatch.setenv("DI_S3_SECRET_KEY", "local-test")
    monkeypatch.setenv("DI_MAX_UPLOAD_BYTES", "1234")
    try:
        assert get_settings() is get_settings()
        assert get_settings().max_upload_bytes == 1234
        for option in ("max_upload_bytes", "relay_batch", "relay_poll_seconds"):
            with pytest.raises(ValidationError):
                Settings(**{option: 0})
    finally:
        get_settings.cache_clear()


def test_s3_does_not_treat_access_denied_as_missing():
    client = Mock()
    store = S3ObjectStore(client, "documents")
    client.head_object.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied"}}, "HeadObject"
    )
    with pytest.raises(ClientError):
        store.exists("demo/a")
    client.head_object.side_effect = ClientError(
        {"Error": {"Code": "404"}}, "HeadObject"
    )
    assert not store.exists("demo/a")


def test_fake_object_size_mismatch_leaves_no_object():
    store = InMemoryObjectStore()
    with pytest.raises(ValueError):
        store.put("a", BytesIO(b"x"), 2, "application/pdf")
    assert not store.exists("a")


def test_resources_check_dependencies_and_close_on_startup_failure(monkeypatch):
    engine, store, client = Mock(), Mock(), Mock()
    engine.connect.return_value.__enter__ = Mock(return_value=Mock())
    engine.connect.return_value.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(runtime, "create_engine", lambda *a, **kw: engine)
    monkeypatch.setattr(runtime.S3ObjectStore, "from_settings", lambda s: store)
    monkeypatch.setattr(runtime.Redis, "from_url", lambda *a, **kw: client)
    settings = Settings(s3_access_key="test", s3_secret_key="test")
    monkeypatch.setattr(runtime, "PostgresRepository", lambda engine: Mock())
    resources = runtime.create_resources(settings)
    resources.ready()
    store.client.head_bucket.assert_called_once_with(Bucket="documents")
    client.ping.assert_called_once()
    resources.close()
    engine.dispose.assert_called_once()
    client.close.assert_called_once()
    store.client.close.assert_called_once()

    def fail(engine):
        raise OSError("database down")

    monkeypatch.setattr(runtime, "PostgresRepository", fail)
    with pytest.raises(OSError):
        runtime.create_resources(settings)
    assert (
        engine.dispose.call_count
        == client.close.call_count
        == store.client.close.call_count
        == 2
    )


def test_relay_stop_does_not_wait_after_shutdown(monkeypatch):
    relay = object.__new__(OutboxRelay)
    stop = Event()
    tenants = []

    def once(tenant, batch):
        tenants.append(tenant)
        stop.set()
        return 1

    monkeypatch.setattr(relay, "run_once", once)
    relay.run("demo", 1, 3600, stop)
    assert tenants == ["demo"]
    with pytest.raises(ValueError):
        OutboxRelay.run_once(relay, "demo", 0)


def test_relay_sigterm_stops_and_restores_handlers(monkeypatch):
    handlers, previous = {}, {}

    def install(sig, handler):
        old = handlers.get(sig, signal.SIG_DFL)
        previous.setdefault(sig, old)
        handlers[sig] = handler
        return old

    settings = Settings(s3_access_key="test", s3_secret_key="test")
    engine, redis = Mock(), Mock()
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli.signal, "signal", install)
    monkeypatch.setattr(cli, "create_engine", lambda *a, **kw: engine)
    monkeypatch.setattr(cli.Redis, "from_url", lambda *a, **kw: redis)

    class Relay:
        def __init__(self, *args):
            pass

        def run(self, tenant, batch, poll, stop):
            assert tenant == "demo" and not stop.is_set()
            handlers[signal.SIGTERM](signal.SIGTERM, None)
            assert stop.is_set()

    monkeypatch.setattr(cli, "OutboxRelay", Relay)
    cli.relay("demo")
    assert handlers == previous
    engine.dispose.assert_called_once()
    redis.close.assert_called_once()


@pytest.mark.parametrize("args", [["relay"], ["relay", "--tenant", "bad/tenant"]])
def test_cli_requires_valid_tenant(monkeypatch, args):
    monkeypatch.setattr("sys.argv", ["di-ingest", *args])
    with pytest.raises(SystemExit) as caught:
        cli.main()
    assert caught.value.code == 2


def test_cli_serve_and_sanitized_failures(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["di-ingest", "serve"])
    settings = Settings(s3_access_key="test", s3_secret_key="test")
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    run = Mock()
    monkeypatch.setattr(cli.uvicorn, "run", run)
    cli.main()
    assert run.call_args.kwargs["host"] == "127.0.0.1"
    assert run.call_args.kwargs["port"] == 8001
    # Containers override the loopback default through the environment.
    monkeypatch.setenv("DI_HTTP_HOST", "0.0.0.0")
    monkeypatch.setenv("DI_HTTP_PORT", "9001")
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: Settings(s3_access_key="test", s3_secret_key="test"),
    )
    cli.main()
    assert run.call_args.kwargs["host"] == "0.0.0.0"
    assert run.call_args.kwargs["port"] == 9001
    run.side_effect = OSError("private content")
    with pytest.raises(SystemExit) as caught:
        cli.main()
    assert caught.value.code == 1
    assert "private" not in capsys.readouterr().err
    run = Mock()
    monkeypatch.setattr(cli, "relay", run)
    tenant = uuid4().hex
    monkeypatch.setattr("sys.argv", ["di-ingest", "relay", "--tenant", tenant])
    cli.main()
    run.assert_called_once_with(tenant)
