"""Generate a development RSA key pair and public JWKS in an ignored directory."""

import argparse
from pathlib import Path

from doc_insight.gateway.dev_identity import generate_keys


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path(".dev-keys"))
    args = parser.parse_args()
    try:
        generate_keys(args.directory)
    except FileExistsError:
        parser.error("directory already exists; choose a new directory for rotation")
    print("Development keys generated. Do not use this issuer in production.")


if __name__ == "__main__":
    main()
