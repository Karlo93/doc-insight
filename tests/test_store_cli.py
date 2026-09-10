import json
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
from doc_insight.testing.embedding import KeywordEmbedder
from doc_insight.testing.storage import InMemoryRepository
from doc_insight.testing.structure import FakeTokenizer
from doc_insight.worker import cli, store_cli
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

FIXTURES = Path(__file__).parent / "fixtures"


def test_default_suite_blocks_native_postgres_connections():
    engine = create_engine("postgresql+psycopg://di:di@127.0.0.1/di")
    with pytest.raises(AssertionError, match="Network access"):
        engine.connect()
    engine.dispose()


@pytest.fixture
def cli_repository(monkeypatch):
    repository = InMemoryRepository(384)
    engine = Mock()
    monkeypatch.setattr(store_cli, "create_engine", lambda *a, **k: engine)
    monkeypatch.setattr(store_cli, "PostgresRepository", lambda engine: repository)
    monkeypatch.setattr(store_cli, "HfTokenizer", lambda settings: FakeTokenizer())
    monkeypatch.setattr(
        store_cli, "FastEmbedEmbedder", lambda settings: KeywordEmbedder()
    )
    yield repository
    assert engine.dispose.called


def invoke(monkeypatch, *args):
    monkeypatch.setattr("sys.argv", ["di", *map(str, args)])
    cli.main()


def test_index_show_search_cli(monkeypatch, capsys, cli_repository):
    invoke(monkeypatch, "index", FIXTURES / "text_hr.pdf", "--tenant", "demo")
    output = capsys.readouterr().out
    assert all(
        f"{stage}=" in output for stage in ("extract", "analyze", "embed", "store")
    )
    assert "Chunks: 1 | Tenant: demo" in output
    stored = next(iter(cli_repository.documents.values()))
    invoke(monkeypatch, "show", stored.id, "--tenant", "demo")
    record = json.loads(capsys.readouterr().out)
    assert record["language"] == record["chunks"][0]["language"] == "hr"
    invoke(monkeypatch, "search", "Marić", "--tenant", "demo", "-k", 1)
    assert "Page 1 | cosine=" in capsys.readouterr().out
    invoke(monkeypatch, "search", "Marić", "--tenant", "other")
    assert capsys.readouterr().out == ""
    with pytest.raises(SystemExit) as error:
        invoke(monkeypatch, "show", stored.id, "--tenant", "other")
    assert error.value.code == 2
    assert "Document not found for tenant" in capsys.readouterr().err


@pytest.mark.parametrize(
    "args",
    [
        ("index", "file.pdf"),
        ("show", "invalid", "--tenant", "a"),
        ("search", "words", "--tenant", ""),
        ("search", "words", "--tenant", "a", "-k", "0"),
    ],
)
def test_invalid_cli_arguments(monkeypatch, args):
    with pytest.raises(SystemExit) as error:
        invoke(monkeypatch, *args)
    assert error.value.code == 2


def test_database_errors_do_not_print_query_parameters(monkeypatch, capsys):
    engine = Mock()
    monkeypatch.setattr(store_cli, "create_engine", lambda *a, **k: engine)
    monkeypatch.setattr(
        store_cli,
        "PostgresRepository",
        Mock(side_effect=SQLAlchemyError("private text")),
    )
    with pytest.raises(SystemExit):
        invoke(monkeypatch, "show", uuid4(), "--tenant", "a")
    assert "private text" not in capsys.readouterr().err
    engine.dispose.assert_called_once()


def test_overlong_question_is_a_clear_cli_error(monkeypatch, capsys, cli_repository):
    embedder = Mock()
    embedder.embed_query.side_effect = ValueError("Input exceeds 126 content tokens")
    monkeypatch.setattr(store_cli, "FastEmbedEmbedder", lambda settings: embedder)
    with pytest.raises(SystemExit) as error:
        invoke(monkeypatch, "search", "question", "--tenant", "a")
    assert error.value.code == 2
    assert "exceeds 126" in capsys.readouterr().err
