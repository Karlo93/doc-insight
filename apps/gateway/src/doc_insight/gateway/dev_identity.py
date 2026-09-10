"""Local demo issuer; private material is generated, never distributed."""

import json
import os
from pathlib import Path
from time import time
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from doc_insight.contracts.gateway import Identity
from doc_insight.gateway.settings import Settings


def generate_keys(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    descriptor = os.open(
        directory / "private.pem", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
    )
    with os.fdopen(descriptor, "wb") as output:
        output.write(private)
    public = key.public_key()
    (directory / "public.pem").write_bytes(
        public.public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(public))
    jwk.update(kid=uuid4().hex, alg="RS256", use="sig")
    (directory / "jwks.json").write_text(json.dumps({"keys": [jwk]}, indent=2))


def mint_token(
    directory: Path, identity: Identity, ttl: int, settings: Settings
) -> str:
    if ttl <= 0:
        raise ValueError("ttl must be positive")
    jwks = json.loads((directory / "jwks.json").read_text())
    now = int(time())
    return jwt.encode(
        {
            "sub": identity.user,
            "tenant": identity.tenant,
            "iat": now,
            "exp": now + ttl,
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
        },
        (directory / "private.pem").read_bytes(),
        algorithm="RS256",
        headers={"kid": jwks["keys"][0]["kid"]},
    )
