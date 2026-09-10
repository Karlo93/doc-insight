import json
from time import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from doc_insight.gateway.auth import Authenticator
from doc_insight.gateway.proxy import Gateway
from doc_insight.gateway.settings import Settings, get_settings
from doc_insight.testing.gateway import FakeJwksSource, FakeRateLimiter, FakeUpstream


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="module", autouse=True)
async def async_runtime(anyio_backend):
    # Initialize asyncio's Windows wakeup socket before the function-level network guard.
    yield


@pytest.fixture(scope="session")
def keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid="test-key", alg="RS256", use="sig")
    return key, jwk


@pytest.fixture
def settings():
    get_settings.cache_clear()
    yield Settings(jwt_leeway_seconds=0)
    get_settings.cache_clear()


@pytest.fixture
def token(keypair, settings):
    def mint(overrides=None, headers=None, algorithm="RS256", missing=()):
        now = int(time())
        claims = {
            "sub": "alice",
            "tenant": "demo",
            "exp": now + 3600,
            "iat": now,
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
        }
        claims.update(overrides or {})
        for field in missing:
            claims.pop(field)
        key = (
            keypair[0]
            if algorithm == "RS256"
            else ("x" * 32 if algorithm == "HS256" else None)
        )
        return jwt.encode(
            claims, key, algorithm=algorithm, headers=headers or {"kid": "test-key"}
        )

    return mint


@pytest.fixture
def gateway(keypair, settings):
    return Gateway(
        settings,
        Authenticator(FakeJwksSource({"keys": [keypair[1]]}), settings),
        FakeRateLimiter(),
        FakeUpstream(),
        FakeUpstream(),
    )
