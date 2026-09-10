import httpx
import pytest
from doc_insight.contracts.gateway import Identity
from doc_insight.gateway.auth import Authenticator, public_jwks, signing_keys
from doc_insight.gateway.dev_identity import generate_keys, mint_token
from doc_insight.gateway.main import create_app, production_gateway
from doc_insight.gateway.settings import Settings
from doc_insight.testing.gateway import FakeJwksSource
from pydantic import ValidationError


@pytest.mark.anyio
async def test_dev_issuer_roundtrip(tmp_path, gateway):
    # Exercise the actual issuer/verifier boundary, not a hand-built fake identity.
    directory = tmp_path / "keys"
    generate_keys(directory)
    with pytest.raises(FileExistsError):
        generate_keys(directory)
    credential = mint_token(
        directory, Identity("demo", "alice"), 3600, gateway.settings
    )
    gateway.settings.dev_jwks_path = directory / "jwks.json"
    app = create_app(gateway)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://gateway"
        ) as client,
    ):
        response = await client.get("/.well-known/jwks.json")
    assert response.status_code == 200
    assert set(response.json()["keys"][0]) == {"kty", "kid", "n", "e"}
    source = FakeJwksSource(response.json())
    assert await Authenticator(source, gateway.settings).authenticate(
        "Bearer " + credential
    ) == Identity("demo", "alice")
    with pytest.raises(ValueError):
        mint_token(directory, Identity("demo", "alice"), 0, gateway.settings)


@pytest.mark.anyio
async def test_production_clients_created_once_and_closed(settings):
    async with production_gateway() as gateway:
        client = gateway.query.client
        assert gateway.ingest.client is client
        assert (
            gateway.query.max_response_bytes
            == gateway.settings.max_upstream_response_bytes
        )
        identity_client = gateway.auth.source.client
        assert identity_client is not client
        assert not identity_client.is_closed
        assert not client.is_closed
    assert client.is_closed
    assert identity_client.is_closed


@pytest.mark.parametrize(
    "changes",
    [
        {"rate_limit_rps": 0},
        {"rate_limit_burst": 0},
        {"max_upload_bytes": 0},
        {"upstream_timeout_seconds": 0},
        {"jwt_leeway_seconds": -1},
        {"jwks_url": "file:///keys"},
        {"redis_url": "http://redis"},
        {"cors_origins": "*"},
        {"cors_origins": "https://example.com/path"},
        {"rate_limit_rps": float("nan")},
        {"rate_limit_rps": float("inf")},
    ],
)
def test_invalid_settings(changes):
    with pytest.raises(ValidationError):
        Settings(**changes)


def test_empty_development_path_and_valid_origins():
    assert Settings(dev_jwks_path="").dev_jwks_path is None
    assert Settings(
        cors_origins="https://example.com,http://localhost:3000"
    ).cors_origins


@pytest.mark.parametrize(
    "changes",
    [
        {"alg": "HS256"},
        {"use": "enc"},
        {"key_ops": ["encrypt"]},
        {"kid": ""},
        {"kty": "oct"},
        {"n": ""},
    ],
)
def test_invalid_signing_keys(keypair, changes):
    with pytest.raises((ValueError, TypeError)):
        signing_keys({"keys": [dict(keypair[1], **changes)]})


def test_duplicate_key_ids_rejected(keypair):
    with pytest.raises(ValueError):
        signing_keys({"keys": [keypair[1], keypair[1]]})


def test_cache_cannot_expire_before_refresh_cooldown():
    with pytest.raises(ValidationError):
        Settings(jwks_cache_seconds=1, jwks_refresh_seconds=5)
    assert Settings(jwks_cache_seconds=5, jwks_refresh_seconds=5)


def test_public_jwks_does_not_promote_encryption_keys(keypair):
    document = {"keys": [keypair[1], dict(keypair[1], kid="encryption", use="enc")]}
    assert [key["kid"] for key in public_jwks(document)["keys"]] == ["test-key"]


def test_cli_serve(monkeypatch, settings):
    from doc_insight.gateway import cli

    calls = []
    monkeypatch.setattr("sys.argv", ["di-gateway", "serve"])
    monkeypatch.setattr(
        cli.uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs))
    )
    cli.main()
    assert calls[0][0] == ("doc_insight.gateway.main:app",)
    assert calls[0][1]["port"] == 8000
    assert calls[0][1]["access_log"] is False
