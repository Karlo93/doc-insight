import asyncio
import json
from time import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from doc_insight.contracts.gateway import Identity
from doc_insight.gateway.auth import Authenticator, InvalidToken
from doc_insight.gateway.http import HttpJwksSource
from doc_insight.testing.gateway import FakeJwksSource

pytestmark = pytest.mark.anyio


async def test_valid_and_cached(gateway, token):
    for _ in range(2):
        assert await gateway.auth.authenticate("Bearer " + token()) == Identity(
            "demo", "alice"
        )
    assert gateway.auth.source.calls == 1


@pytest.mark.parametrize(
    "claims,missing,algorithm,headers",
    [
        ({"exp": int(time()) - 60}, (), "RS256", None),
        ({"iss": "wrong"}, (), "RS256", None),
        ({"aud": "wrong"}, (), "RS256", None),
        ({}, (), "HS256", None),
        ({}, (), "none", None),
        ({}, ("tenant",), "RS256", None),
        ({"tenant": "bad/tenant"}, (), "RS256", None),
        ({"tenant": "x" * 65}, (), "RS256", None),
        ({"tenant": "x\n"}, (), "RS256", None),
        ({"tenant": 1}, (), "RS256", None),
        ({"sub": "bad\r\nheader"}, (), "RS256", None),
        ({"sub": ""}, (), "RS256", None),
        ({"sub": "ž"}, (), "RS256", None),
        ({"iat": int(time()) + 3600}, (), "RS256", None),
        ({"exp": True}, (), "RS256", None),
        ({"iat": "123"}, (), "RS256", None),
        ({}, ("sub",), "RS256", None),
        ({}, ("exp",), "RS256", None),
        ({}, ("iat",), "RS256", None),
        ({}, ("iss",), "RS256", None),
        ({}, ("aud",), "RS256", None),
        ({}, (), "RS256", {"kid": "unknown"}),
        ({}, (), "RS256", {"typ": "JWT"}),
    ],
)
async def test_rejections(gateway, token, claims, missing, algorithm, headers):
    credential = token(claims, missing=missing, algorithm=algorithm, headers=headers)
    with pytest.raises(InvalidToken, match="^invalid token$"):
        await gateway.auth.authenticate("Bearer " + credential)


@pytest.mark.parametrize(
    "authorization", ["", "Basic abc", "Bearer", "Bearer a b", "Bearer malformed"]
)
async def test_malformed(gateway, authorization):
    with pytest.raises(InvalidToken):
        await gateway.auth.authenticate(authorization)


async def test_tampered_signature(gateway, token):
    parts = token().split(".")
    parts[2] = ("A" if parts[2][0] != "A" else "B") + parts[2][1:]
    with pytest.raises(InvalidToken):
        await gateway.auth.authenticate("Bearer " + ".".join(parts))


async def test_rotation_refresh_singleflight_and_expiry(keypair, settings, token):
    now = [0.0]
    source = FakeJwksSource({"keys": [keypair[1]]})
    auth = Authenticator(source, settings, lambda: now[0])
    await auth.authenticate("Bearer " + token())
    rotated = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(rotated.public_key()))
    jwk["kid"] = "rotated"
    claims = jwt.decode(token(), options={"verify_signature": False})
    new_token = jwt.encode(
        claims, rotated, algorithm="RS256", headers={"kid": "rotated"}
    )
    source.document = {"keys": [keypair[1], jwk]}
    with pytest.raises(InvalidToken):
        await auth.authenticate("Bearer " + new_token)
    assert source.calls == 1
    now[0] += settings.jwks_refresh_seconds
    results = await asyncio.gather(
        *[auth.authenticate("Bearer " + new_token) for _ in range(50)]
    )
    assert all(result == Identity("demo", "alice") for result in results)
    assert source.calls == 2
    source.document = {"keys": [jwk]}
    now[0] += settings.jwks_cache_seconds
    with pytest.raises(InvalidToken):
        await auth.authenticate("Bearer " + token())
    assert source.calls == 3


async def test_failed_refresh_is_bounded(settings, token):
    now = [0.0]
    source = FakeJwksSource({"keys": []})
    auth = Authenticator(source, settings, lambda: now[0])
    for _ in range(50):
        with pytest.raises(InvalidToken):
            await auth.authenticate("Bearer " + token())
    assert source.calls == 1


@pytest.mark.parametrize("provider", ["fake", "http"])
async def test_jwks_source_contract(provider, keypair, settings, token):
    document = {"keys": [keypair[1]]}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=document))
    ) as client:
        source = (
            FakeJwksSource(document)
            if provider == "fake"
            else HttpJwksSource(client, "http://issuer/jwks")
        )
        assert await source.fetch() == document
        assert await Authenticator(source, settings).authenticate(
            "Bearer " + token()
        ) == Identity("demo", "alice")


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, text="private failure"),
        httpx.Response(200, text="bad JSON"),
        httpx.Response(200, json=[]),
        httpx.Response(200, content=b"x" * 300000),
        httpx.Response(302, headers={"location": "http://other/key"}),
    ],
)
async def test_provider_failures_are_unauthorized(response, settings, token):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: response)
    ) as client:
        auth = Authenticator(HttpJwksSource(client, "http://issuer/jwks"), settings)
        with pytest.raises(InvalidToken, match="^invalid token$"):
            await auth.authenticate("Bearer " + token())


async def test_leeway(gateway, token):
    gateway.settings.jwt_leeway_seconds = 30
    assert await gateway.auth.authenticate("Bearer " + token({"exp": int(time()) - 10}))
