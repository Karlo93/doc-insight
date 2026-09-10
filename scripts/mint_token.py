"""Print a short-lived development token for one tenant and user."""

import argparse
from pathlib import Path

from doc_insight.contracts.gateway import Identity
from doc_insight.gateway.dev_identity import mint_token
from doc_insight.gateway.settings import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path(".dev-keys"))
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--ttl", type=int, default=3600)
    args = parser.parse_args()
    try:
        token = mint_token(
            args.directory, Identity(args.tenant, args.user), args.ttl, get_settings()
        )
    except (ValueError, OSError):
        parser.error("invalid identity, ttl or development key directory")
    print(token)


if __name__ == "__main__":
    main()
