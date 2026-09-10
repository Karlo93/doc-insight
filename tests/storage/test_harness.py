import pytest


@pytest.mark.parametrize(
    "url,allowed",
    [
        ("postgresql+psycopg://di:di@localhost:5432/di", True),
        ("postgresql+psycopg://di:di@127.0.0.1:55432/di", True),
        ("postgresql+psycopg://di:di@db.example.internal:5432/di", False),
    ],
)
def test_temporary_databases_refuse_remote_hosts_before_connecting(
    monkeypatch: pytest.MonkeyPatch, temporary_database_factory, url: str, allowed: bool
) -> None:
    monkeypatch.setenv("DI_DATABASE_URL", url)
    monkeypatch.delenv("DI_ALLOW_REMOTE_TEST_DB", raising=False)
    # The default suite blocks connections, so a local URL fails only at connect time.
    expected = AssertionError if allowed else RuntimeError
    with pytest.raises(expected), temporary_database_factory():
        pass


def test_remote_hosts_need_an_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch, temporary_database_factory
) -> None:
    monkeypatch.setenv(
        "DI_DATABASE_URL", "postgresql+psycopg://di:di@db.example.internal/di"
    )
    monkeypatch.setenv("DI_ALLOW_REMOTE_TEST_DB", "1")
    with (
        pytest.raises(AssertionError, match="Network access"),
        temporary_database_factory(),
    ):
        pass
