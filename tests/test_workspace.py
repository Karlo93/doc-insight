import importlib

import pytest


@pytest.mark.parametrize(
    "member",
    [
        "gateway",
        "ingest",
        "query",
        "worker",
        "contracts",
        "domain",
        "observability",
        "testing",
    ],
)
def test_workspace_member_is_importable(member: str) -> None:
    # Import every workspace member to catch packaging omissions before any service starts.
    assert importlib.import_module(f"doc_insight.{member}").__version__ == "0.1.0"
