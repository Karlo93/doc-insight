"""Create private local credentials once; never rotate an existing deployment."""

import os
import secrets
from pathlib import Path


def configure(root: Path) -> bool:
    """Create .env exclusively, preserving any existing credentials and port choices."""
    target = root / ".env"
    if target.exists():
        return False
    template = (root / ".env.example").read_text(encoding="utf-8")
    values = {
        "POSTGRES_PASSWORD": secrets.token_hex(24),
        "DI_DB_RUNTIME_PASSWORD": secrets.token_hex(24),
        "DI_S3_ACCESS_KEY": "di" + secrets.token_hex(8),
        "DI_S3_SECRET_KEY": secrets.token_hex(24),
        "GRAFANA_ADMIN_PASSWORD": secrets.token_hex(24),
    }
    for key, user, password in (
        ("DATABASE_URL", "di_app", values["DI_DB_RUNTIME_PASSWORD"]),
        ("MIGRATION_DATABASE_URL", "di", values["POSTGRES_PASSWORD"]),
    ):
        values[f"DI_{key}"] = (
            f"postgresql+psycopg://{user}:{password}@127.0.0.1:5432/di"
        )
        values[f"DI_CONTAINER_{key}"] = (
            f"postgresql+psycopg://{user}:{password}@db:5432/di"
        )
    lines = [
        f"{line.split('=', 1)[0]}={values[line.split('=', 1)[0]]}"
        if line.split("=", 1)[0] in values
        else line
        for line in template.splitlines()
    ]
    # O_EXCL closes the existence-check race; no second process can overwrite a key.
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(lines) + "\n")
    return True


if __name__ == "__main__":
    created = configure(Path(__file__).resolve().parents[1])
    print(
        "Created private .env; configure ports before starting."
        if created
        else ".env exists; unchanged."
    )
