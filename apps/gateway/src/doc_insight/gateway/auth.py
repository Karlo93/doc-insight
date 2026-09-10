"""RS256 validation with a bounded, single-flight JWKS cache."""

import asyncio
import json
from collections.abc import Callable
from time import monotonic
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from doc_insight.contracts.gateway import Identity, JwksSource
from doc_insight.gateway.settings import Settings


class InvalidToken(Exception):
    """Authentication failures deliberately share one public message."""


def signing_keys(document: dict[str, Any]) -> dict[str, jwt.PyJWK]:
    """Validate usable public RS256 keys; reject weak or ambiguous key sets."""
    result = {}
    for item in document["keys"]:
        if item.get("kty") != "RSA" or item.get("alg", "RS256") != "RS256":
            continue
        if item.get("use", "sig") != "sig" or "verify" not in item.get(
            "key_ops", ["verify"]
        ):
            continue
        kid = item.get("kid")
        key = jwt.PyJWK(item, algorithm="RS256")
        if not isinstance(key.key, RSAPublicKey) or key.key.key_size < 2048:
            raise ValueError("Invalid signing key")
        if not isinstance(kid, str) or not kid or kid in result or "d" in item:
            raise ValueError("Invalid key identifier")
        result[kid] = key
    if not result:
        raise ValueError("No signing keys")
    return result


def public_jwks(document: dict[str, Any]) -> dict[str, Any]:
    """Rebuild the validated key set using only public RSA parameters."""
    result = []
    for kid, key in signing_keys(document).items():
        raw = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.key))
        result.append({name: raw[name] for name in ("kty", "n", "e")} | {"kid": kid})
    return {"keys": result}


class Authenticator:
    def __init__(
        self,
        source: JwksSource,
        settings: Settings,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.source, self.settings, self.clock = source, settings, clock
        self.keys: dict[str, jwt.PyJWK] = {}
        self.expires = float("-inf")
        self.next_refresh = float("-inf")
        self.lock = asyncio.Lock()

    async def key(self, kid: str) -> jwt.PyJWK:
        """Resolve a signing key with serialized refresh and bounded cache lifetime."""
        async with self.lock:
            now = self.clock()
            if (
                kid not in self.keys or now >= self.expires
            ) and now >= self.next_refresh:
                # Back off even on failure: arbitrary kids must not amplify IdP traffic.
                self.next_refresh = now + self.settings.jwks_refresh_seconds
                self.keys = signing_keys(await self.source.fetch())
                self.expires = self.clock() + self.settings.jwks_cache_seconds
            if self.clock() >= self.expires or kid not in self.keys:
                raise InvalidToken
            return self.keys[kid]

    async def authenticate(self, authorization: str) -> Identity:
        """Verify signature and required claims before returning a tenant identity."""
        try:
            scheme, token = authorization.split()
            if scheme.lower() != "bearer" or len(token) > 16384:
                raise InvalidToken
            # The unverified header selects a key; only jwt.decode establishes identity.
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            if header.get("alg") != "RS256" or not isinstance(kid, str) or not kid:
                raise InvalidToken
            claims = jwt.decode(
                token,
                await self.key(kid),
                algorithms=["RS256"],
                issuer=self.settings.jwt_issuer,
                audience=self.settings.jwt_audience,
                leeway=self.settings.jwt_leeway_seconds,
                options={"require": ["sub", "tenant", "exp", "iat", "iss", "aud"]},
            )
            if not all(isinstance(claims[k], str) for k in ("tenant", "sub")):
                raise InvalidToken
            if any(type(claims[k]) is not int for k in ("exp", "iat")):
                raise InvalidToken
            return Identity(claims["tenant"], claims["sub"])
        except (
            InvalidToken,
            jwt.PyJWTError,
            httpx.HTTPError,
            TimeoutError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            OverflowError,
        ):
            # Library, key parsing and provider errors all fail authentication closed.
            raise InvalidToken("invalid token") from None
