"""Credential bootstrap must be unique and must never rotate an existing database."""

import runpy
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/configure_local.py"
CONFIGURE = runpy.run_path(str(SCRIPT))["configure"]
TEMPLATE = SCRIPT.parents[1] / ".env.example"


def configuration(root):
    root.mkdir()
    (root / ".env.example").write_bytes(TEMPLATE.read_bytes())
    CONFIGURE(root)
    return dict(
        line.split("=", 1)
        for line in (root / ".env").read_text().splitlines()
        if line and not line.startswith("#")
    )


def test_new_installations_have_distinct_secrets_and_matching_urls(tmp_path):
    first, second = configuration(tmp_path / "one"), configuration(tmp_path / "two")
    # A shared template must not turn separate installations into shared credentials.
    for key in (
        "POSTGRES_PASSWORD",
        "DI_DB_RUNTIME_PASSWORD",
        "DI_S3_SECRET_KEY",
        "GRAFANA_ADMIN_PASSWORD",
    ):
        assert len(first[key]) >= 48 and first[key] != second[key]
    assert first["POSTGRES_PASSWORD"] != first["DI_DB_RUNTIME_PASSWORD"]
    assert first["DI_DB_RUNTIME_PASSWORD"] in first["DI_CONTAINER_DATABASE_URL"]
    assert first["POSTGRES_PASSWORD"] in first["DI_MIGRATION_DATABASE_URL"]
    assert first["DI_OPENAI_API_KEY"] == ""


def test_existing_environment_is_preserved_byte_for_byte(tmp_path):
    expected = b"EXISTING_CONFIGURATION=preserve\n"
    (tmp_path / ".env").write_bytes(expected)
    assert CONFIGURE(tmp_path) is False
    assert (tmp_path / ".env").read_bytes() == expected


def test_concurrent_creation_cannot_truncate_existing_credentials(
    tmp_path, monkeypatch
):
    configuration(tmp_path / "one")
    existing = tmp_path / "one" / ".env"
    expected = existing.read_bytes()
    # Simulate another process creating the file immediately after the early check.
    monkeypatch.setattr(Path, "exists", lambda self: False)
    with pytest.raises(FileExistsError):
        CONFIGURE(tmp_path / "one")
    assert existing.read_bytes() == expected
