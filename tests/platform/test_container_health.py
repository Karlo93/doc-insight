"""Container probes must fail for expired heartbeats and failed HTTP liveness."""

import runpy
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "container_health.py"


@pytest.mark.parametrize("ttl", [-2, -1, 0, 1, 30, None])
def test_worker_requires_unexpired_heartbeat(monkeypatch, ttl):
    # Process liveness alone is insufficient; a worker must have a current progress heartbeat.
    monkeypatch.setenv("DI_CONTAINER_APP", "worker")
    monkeypatch.setenv("DI_REDIS_URL", "redis://redis:6379/0")
    client = MagicMock()
    # None models a host without any per-process heartbeat key.
    client.scan_iter.return_value = [] if ttl is None else [b"di:worker:consumer-1-42"]
    client.ttl.return_value = ttl
    factory = MagicMock()
    factory.from_url.return_value.__enter__.return_value = client
    monkeypatch.setitem(sys.modules, "redis", SimpleNamespace(Redis=factory))
    monkeypatch.setattr("socket.gethostname", lambda: "consumer-1")
    check = runpy.run_path(str(SCRIPT))["check"]
    if ttl is None or ttl <= 0:
        with pytest.raises(RuntimeError, match="heartbeat expired"):
            check()
    else:
        check()
    client.scan_iter.assert_called_once_with("di:worker:consumer-1-*")
    if ttl is not None:
        client.ttl.assert_called_once_with(b"di:worker:consumer-1-42")


@pytest.mark.parametrize(
    "app,port", [("gateway", 8000), ("ingest", 8001), ("query", 8002)]
)
@pytest.mark.parametrize("status", [200, 503])
def test_http_probes_the_service_health_endpoint(monkeypatch, app, port, status):
    monkeypatch.setenv("DI_CONTAINER_APP", app)
    monkeypatch.delenv("DI_CONTAINER_ROLE", raising=False)
    request = MagicMock()
    request.return_value.__enter__.return_value.status = status
    monkeypatch.setattr("urllib.request.urlopen", request)
    check = runpy.run_path(str(SCRIPT))["check"]
    if status == 503:
        with pytest.raises(RuntimeError, match="HTTP process is unhealthy"):
            check()
    else:
        check()
    route = "readyz" if app == "query" else "healthz"
    request.assert_called_once_with(f"http://127.0.0.1:{port}/{route}", timeout=3)


@pytest.mark.parametrize("command", [b"python\0di-ingest\0relay\0", b"python\0other\0"])
def test_relay_probe_checks_the_running_command(monkeypatch, command):
    monkeypatch.setenv("DI_CONTAINER_APP", "ingest")
    monkeypatch.setenv("DI_CONTAINER_ROLE", "relay")
    monkeypatch.setattr(Path, "read_bytes", lambda self: command)
    check = runpy.run_path(str(SCRIPT))["check"]
    if b"relay" in command:
        check()
    else:
        with pytest.raises(RuntimeError, match="Relay process is absent"):
            check()
