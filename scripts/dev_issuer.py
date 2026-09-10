"""Development issuer inside the gateway image: private key in its own volume, JWKS published."""

import argparse
import shutil
from pathlib import Path

from doc_insight.contracts.gateway import Identity
from doc_insight.gateway.dev_identity import generate_keys, mint_token
from doc_insight.gateway.settings import get_settings

ISSUER = Path("/issuer/keys")
PUBLIC = Path("/jwks/jwks.json")


def ensure() -> None:
    if not (ISSUER / "jwks.json").exists():
        # A half-written directory from an interrupted run must not block startup.
        shutil.rmtree(ISSUER, ignore_errors=True)
        generate_keys(ISSUER)
    shutil.copyfile(ISSUER / "jwks.json", PUBLIC)
    print("Development JWKS published; the private key stays in the issuer volume.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("ensure")
    mint = commands.add_parser("mint")
    mint.add_argument("--tenant", required=True)
    mint.add_argument("--user", required=True)
    mint.add_argument("--ttl", type=int, default=3600)
    args = parser.parse_args()
    if args.command == "ensure":
        ensure()
        return
    print(
        mint_token(ISSUER, Identity(args.tenant, args.user), args.ttl, get_settings())
    )


if __name__ == "__main__":
    main()
