import argparse
import signal
from contextlib import ExitStack
from threading import Event
from unittest.mock import Mock

import pytest
from doc_insight.worker import cli, worker_cli
from doc_insight.worker.settings import Settings
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError


def test_signal_handlers_finish_first_and_exit_immediately_second(monkeypatch):
    handlers = {}
    monkeypatch.setattr(
        signal, "signal", lambda signum, handler: handlers.setdefault(signum, handler)
    )
    monkeypatch.setattr(worker_cli.os, "_exit", Mock())
    stopping = Event()
    with ExitStack() as stack:
        worker_cli.install_signals(stopping, stack)
        handlers[signal.SIGTERM](signal.SIGTERM, None)
        assert stopping.is_set()
        worker_cli.os._exit.assert_not_called()
        handlers[signal.SIGTERM](signal.SIGTERM, None)
        worker_cli.os._exit.assert_called_once_with(0)


def test_cli_worker_run_dispatch_and_invalid_settings(monkeypatch, capsys):
    serve = Mock()
    monkeypatch.setattr(worker_cli, "serve", serve)
    monkeypatch.setattr("sys.argv", ["di", "worker", "run"])
    cli.main()
    assert isinstance(serve.call_args.args[0], Settings)
    monkeypatch.setenv("DI_WORKER_BATCH", "0")
    worker_cli.get_settings.cache_clear()
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
    assert "Invalid worker settings" in capsys.readouterr().err


@pytest.mark.parametrize(
    "settings",
    [
        {"worker_group": " "},
        {"worker_block_ms": 0},
        {"worker_block_ms": 30000},
        {"worker_batch": 0},
        {"worker_reclaim_seconds": 0},
        {"worker_claim_min_idle_ms": 0},
        {"worker_max_attempts": 0},
    ],
)
def test_settings_reject_unsafe_loop_values(settings):
    with pytest.raises(ValidationError):
        Settings(**settings)


def test_runtime_builds_once_and_closes_all_clients(monkeypatch):
    redis, engine, s3, worker = Mock(), Mock(), Mock(), Mock()
    monkeypatch.setattr(worker_cli.Redis, "from_url", Mock(return_value=redis))
    monkeypatch.setattr(worker_cli, "create_engine", Mock(return_value=engine))
    monkeypatch.setattr(worker_cli.boto3, "client", Mock(return_value=s3))
    monkeypatch.setattr(worker_cli, "PostgresRepository", Mock())
    monkeypatch.setattr(worker_cli, "Worker", Mock(return_value=worker))
    worker_cli.serve(Settings())
    worker.run.assert_called_once()
    redis.close.assert_called_once()
    engine.dispose.assert_called_once()
    s3.close.assert_called_once()
    assert worker_cli.Worker.call_args.args[3].endswith(f"-{worker_cli.os.getpid()}")


def test_startup_database_retry_and_signal_interruption(monkeypatch, caplog):
    stopping = Event()
    monkeypatch.setattr(worker_cli, "Event", lambda: stopping)

    def fail(*args):
        stopping.set()
        raise OperationalError("private SQL", {}, Exception("private"))

    monkeypatch.setattr(worker_cli, "build_worker", fail)
    worker_cli.serve(Settings())
    assert "OperationalError" in caplog.text and "private" not in caplog.text


def test_startup_error_is_sanitized(monkeypatch, capsys):
    monkeypatch.setattr(worker_cli, "serve", Mock(side_effect=ValueError("private")))
    with pytest.raises(SystemExit):
        worker_cli.run(argparse.ArgumentParser())
    assert "private" not in capsys.readouterr().err
