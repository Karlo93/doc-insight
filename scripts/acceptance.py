"""Real HTTP acceptance using generated fixtures; tokens and outputs stay untracked."""

import argparse
import json
import time
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]


def upload(client: httpx.Client, name: str, data: bytes, media: str) -> tuple[str, str]:
    trace = uuid4().hex
    response = client.post(
        "/ingest",
        files={"file": (name, data, media)},
        headers={"traceparent": f"00-{trace}-0123456789abcdef-01"},
    )
    response.raise_for_status()
    body = response.json()
    return body["document_id"], trace


def await_processed(client: httpx.Client, identifier: str) -> dict:
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        response = client.get(f"/documents/{identifier}")
        response.raise_for_status()
        body = response.json()
        if body["status"] == "processed":
            return body
        if body["status"] == "failed":
            raise RuntimeError("Fixture processing failed")
        time.sleep(2)
    raise TimeoutError("Processing exceeded 600 seconds")


def ask(client: httpx.Client, question: str, identifier: str | None = None) -> dict:
    response = client.post(
        "/query",
        json={
            "question": question,
            "top_k": 5,
            "filter": {"document_ids": [identifier]} if identifier else {},
        },
    )
    response.raise_for_status()
    return response.json()


def run(client: httpx.Client, other: httpx.Client) -> dict:
    evidence: dict = {"uploads": [], "queries": []}
    fixture_dir = ROOT / "tests/fixtures"
    for name, media in [
        ("text_en.pdf", "application/pdf"),
        ("text_hr.pdf", "application/pdf"),
        ("scanned.png", "image/png"),
    ]:
        identifier, trace = upload(
            client, name, (fixture_dir / name).read_bytes(), media
        )
        started = time.monotonic()
        await_processed(client, identifier)
        evidence["uploads"].append(
            {
                "fixture": name,
                "id": identifier,
                "trace_id": trace,
                "processing_seconds": round(time.monotonic() - started, 2),
            }
        )
        assert other.get(f"/documents/{identifier}").status_code == 404
        print(f"PASS upload/process/isolation: {name}", flush=True)
    en, hr = (evidence["uploads"][i]["id"] for i in range(2))
    for question, identifier, expected in [
        ("Where did Alice Johnson visit?", en, "London"),
        ("Gdje živi Marko Marić?", hr, "Zagreb"),
    ]:
        result = ask(client, question, identifier)
        assert (
            not result["abstained"]
            and expected.casefold() in result["answer"].casefold()
        ), result
        assert result["generation"]["provider"] == "openai"
        assert result["generation"]["usage"]["input_tokens"] > 0
        assert result["sources"] and all(
            source["document_id"] == identifier for source in result["sources"]
        )
        evidence["queries"].append(result)
        print("PASS supported OpenAI answer with citations and usage", flush=True)
    result = ask(client, "Who won the football world cup in 2014?", en)
    assert result["abstained"] and not result["answer"]
    evidence["queries"].append(result)
    assert ask(other, "Where did Alice Johnson visit?", en)["abstained"]
    # Independent outbox progress proves both provisioned tenants are serviced.
    identifier, _ = upload(
        other,
        "other.pdf",
        (fixture_dir / "text_en.pdf").read_bytes(),
        "application/pdf",
    )
    await_processed(other, identifier)
    assert client.get(f"/documents/{identifier}").status_code == 404
    data = (fixture_dir / "text_en.pdf").read_bytes()
    data += b"\n%" + b"0" * (10 * 1024 * 1024 - len(data)) + b"\n"
    identifier, trace = upload(client, "ten-mib.pdf", data, "application/pdf")
    await_processed(client, identifier)
    evidence["large_upload"] = {"bytes": len(data), "id": identifier, "trace_id": trace}
    evidence["usage"] = client.get("/usage").json()
    print("PASS abstention, second-tenant relay, 10 MiB upload", flush=True)
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:5080")
    parser.add_argument(
        "--tokens", type=Path, default=Path(".cache/access-tokens.json")
    )
    parser.add_argument("--output", type=Path, default=Path(".cache/acceptance.json"))
    args = parser.parse_args()
    tokens = json.loads(args.tokens.read_text())
    with (
        httpx.Client(
            base_url=args.base,
            headers={"Authorization": f"Bearer {tokens[0]}"},
            timeout=120,
            trust_env=False,
        ) as client,
        httpx.Client(
            base_url=args.base,
            headers={"Authorization": f"Bearer {tokens[1]}"},
            timeout=120,
            trust_env=False,
        ) as other,
    ):
        assert httpx.get(f"{args.base}/documents", trust_env=False).status_code == 401
        evidence = run(client, other)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("Acceptance passed; evidence written without credentials.")


if __name__ == "__main__":
    main()
