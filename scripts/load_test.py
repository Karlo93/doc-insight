"""Bounded open-loop HTTP benchmark. Provider generation must be disabled first."""

import argparse
import asyncio
import json
import time
from collections import Counter
from pathlib import Path

import httpx


def percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    return (
        round(ordered[min(len(ordered) - 1, int((len(ordered) - 1) * percentile))], 2)
        if ordered
        else 0
    )


async def scenario(
    base: str, tokens: list[str], rate: int, seconds: int, mode: str
) -> dict:
    rows: list[dict] = []
    active: set[asyncio.Task] = set()
    limits = httpx.Limits(max_connections=256, max_keepalive_connections=100)
    async with httpx.AsyncClient(
        base_url=base, limits=limits, timeout=30, trust_env=False
    ) as client:

        async def send(index: int, scheduled: float) -> None:
            started = time.perf_counter()
            headers = {"Authorization": f"Bearer {tokens[index % len(tokens)]}"}
            try:
                if mode == "query":
                    response = await client.post(
                        "/query",
                        headers=headers,
                        json={"question": "Where did Alice Johnson visit?", "top_k": 5},
                    )
                else:
                    response = await client.get("/documents?limit=20", headers=headers)
                status = str(response.status_code)
            except httpx.HTTPError:
                status = "transport_error"
            rows.append(
                {
                    "status": status,
                    "latency_ms": (time.perf_counter() - scheduled) * 1000,
                    "dispatch_lag_ms": (started - scheduled) * 1000,
                }
            )

        started = time.perf_counter()
        for index in range(rate * seconds):
            scheduled = started + index / rate
            await asyncio.sleep(max(0, scheduled - time.perf_counter()))
            if len(active) >= 256:
                rows.append(
                    {"status": "client_dropped", "latency_ms": 0, "dispatch_lag_ms": 0}
                )
                continue
            task = asyncio.create_task(send(index, scheduled))
            active.add(task)
            task.add_done_callback(active.discard)
        await asyncio.gather(*active)
        elapsed = time.perf_counter() - started
    counts = Counter(row["status"] for row in rows)
    successful = [row["latency_ms"] for row in rows if row["status"] == "200"]
    return {
        "mode": mode,
        "offered_rps": rate,
        "duration_seconds": seconds,
        "elapsed_with_drain": round(elapsed, 2),
        "completed_rps": round(len(successful) / elapsed, 2),
        "statuses": dict(counts),
        "success_percent": round(100 * len(successful) / len(rows), 2),
        "p50_ms": percentile(successful, 0.5),
        "p95_ms": percentile(successful, 0.95),
        "p99_ms": percentile(successful, 0.99),
        "dispatch_p99_ms": percentile([r["dispatch_lag_ms"] for r in rows], 0.99),
        "samples": rows,
    }


async def run(args: argparse.Namespace) -> None:
    tokens = json.loads(args.tokens.read_text())[2:]
    with httpx.Client(base_url=args.base, timeout=120, trust_env=False) as client:
        response = client.post(
            "/query",
            headers={"Authorization": f"Bearer {tokens[0]}"},
            json={"question": "Where did Alice Johnson visit?"},
        )
        response.raise_for_status()
        if response.json()["generation"]["provider"] != "extractive":
            raise RuntimeError(
                "Refusing billable load test: disable OpenAI generation first"
            )
    results = []
    for mode in args.modes.split(","):
        for rate in map(int, args.rates.split(",")):
            result = await scenario(args.base, tokens, rate, args.seconds, mode)
            results.append(result)
            print(
                json.dumps(
                    {key: value for key, value in result.items() if key != "samples"}
                ),
                flush=True,
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps({"results": results}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:5080")
    parser.add_argument(
        "--tokens", type=Path, default=Path(".cache/access-tokens.json")
    )
    parser.add_argument("--output", type=Path, default=Path(".cache/load-results.json"))
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--rates", default="10,25,50,100")
    parser.add_argument("--modes", default="documents,query")
    args = parser.parse_args()
    if (
        args.seconds < 1
        or args.seconds > 1800
        or any(rate < 1 or rate > 200 for rate in map(int, args.rates.split(",")))
        or not set(args.modes.split(",")).issubset({"documents", "query"})
    ):
        parser.error("Use 1–1800 seconds, rates 1–200, and documents/query modes")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
