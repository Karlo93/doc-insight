"""The issuer job publishes only the JWKS and mints tokens the gateway accepts."""

import json
import runpy
import sys
from pathlib import Path

import jwt
import pytest
from doc_insight.gateway.auth import signing_keys

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "dev_issuer.py"


def test_ensure_is_idempotent_and_mint_matches_published_keys(
    tmp_path, monkeypatch, capsys
):
    # Restarting the issuer must preserve keys so existing workspace tokens remain valid.
    functions = runpy.run_path(str(SCRIPT))
    # run_path returns a copy; the functions read their own globals.
    module = functions["ensure"].__globals__
    module["ISSUER"] = tmp_path / "issuer" / "keys"
    module["PUBLIC"] = tmp_path / "jwks" / "jwks.json"
    module["PUBLIC"].parent.mkdir()
    module["ISSUER"].mkdir(parents=True)  # left behind by an interrupted run
    module["ensure"]()
    first = module["PUBLIC"].read_text()
    module["ensure"]()
    assert module["PUBLIC"].read_text() == first
    assert list(module["PUBLIC"].parent.iterdir()) == [module["PUBLIC"]]
    monkeypatch.setattr(
        sys, "argv", ["dev_issuer", "mint", "--tenant", "demo", "--user", "alice"]
    )
    module["main"]()
    token = capsys.readouterr().out.strip().splitlines()[-1]
    keys = signing_keys(json.loads(first))
    key = keys[jwt.get_unverified_header(token)["kid"]]
    claims = jwt.decode(token, key, algorithms=["RS256"], audience="doc-insight")
    assert claims["tenant"] == "demo" and claims["sub"] == "alice"
    monkeypatch.setattr(sys, "argv", ["dev_issuer", "mint", "--tenant", "demo"])
    with pytest.raises(SystemExit):
        module["main"]()
