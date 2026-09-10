"""Render recorded 100 req/s results with explicit accounting for failed work."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent


def delivery_counts(row: dict) -> tuple[int, int, int, int]:
    """Separate driver drops from HTTP/transport failures; reject missing samples."""
    total = row["offered_rps"] * row["duration_seconds"]
    statuses = row["statuses"]
    if total <= 0 or sum(statuses.values()) != total:
        raise ValueError("Status counts must account for every scheduled request")
    success = statuses.get("200", 0)
    dropped = statuses.get("client_dropped", 0)
    return total, success, dropped, total - success - dropped


def plot_throughput(axis, rows: list[dict], labels: list[str]) -> None:
    axis.bar(
        labels, [row["completed_rps"] for row in rows], color=["#267663", "#b34f32"]
    )
    axis.axhline(100, color="#666666", linestyle="--", linewidth=1)
    axis.set(
        title="Successful throughput",
        ylabel="Requests/s including drain",
        ylim=(0, 120),
    )
    for index, row in enumerate(rows):
        axis.text(
            index, row["completed_rps"] + 3, f"{row['completed_rps']:.2f}", ha="center"
        )


def plot_delivery(axis, rows: list[dict], labels: list[str]) -> None:
    counts = [delivery_counts(row) for row in rows]
    success = [100 * ok / total for total, ok, _, _ in counts]
    dropped = [100 * drop / total for total, _, drop, _ in counts]
    failures = [100 * failed / total for total, _, _, failed in counts]
    axis.bar(labels, success, color="#267663", label="HTTP 200")
    axis.bar(labels, dropped, bottom=success, color="#b34f32", label="Client dropped")
    if any(failures):
        axis.bar(
            labels,
            failures,
            bottom=[ok + drop for ok, drop in zip(success, dropped, strict=True)],
            color="#5c6173",
            label="HTTP / transport error",
        )
    axis.set(
        title="Delivery of all scheduled work",
        ylabel="Percent of offered requests",
        ylim=(0, 140),
    )
    axis.legend(loc="upper right", fontsize=9)
    for index, (total, ok, _, _) in enumerate(counts):
        axis.text(index, 102, f"{ok:,} / {total:,}", ha="center", fontsize=9)


def plot_latency(axis, rows: list[dict], labels: list[str]) -> None:
    axis.bar(labels, [row["p95_ms"] for row in rows], color=["#267663", "#b34f32"])
    axis.set(
        title="Successful response latency",
        ylabel="p95 milliseconds (log scale)",
        yscale="log",
        ylim=(1, 40000),
    )
    for index, row in enumerate(rows):
        axis.text(
            index,
            row["p95_ms"] * 1.15,
            f"{row['p95_ms']:,.2f} ms",
            ha="center",
            fontsize=9,
        )


def main() -> None:
    results = json.loads((ROOT / "results.json").read_text(encoding="utf-8"))[
        "confirmation"
    ]
    rows = sorted(
        (row for row in results if row["offered_rps"] == 100),
        key=lambda row: row["mode"],
    )
    if [row["mode"] for row in rows] != ["documents", "query"]:
        raise ValueError("Expected one 100 req/s confirmation per endpoint")
    durations = {row["duration_seconds"] for row in rows}
    if len(durations) != 1:
        raise ValueError("Compare endpoint runs with equal scheduled durations")
    duration = durations.pop()
    labels = ["GET /documents", "POST /query"]
    plt.rcParams.update(
        {"font.size": 11, "axes.spines.top": False, "axes.spines.right": False}
    )
    fig, axes = plt.subplots(1, 3, figsize=(15, 5), constrained_layout=True)
    fig.suptitle(
        f"100 offered requests/s · {duration} seconds · hosted generation disabled"
    )
    plot_throughput(axes[0], rows, labels)
    plot_delivery(axes[1], rows, labels)
    plot_latency(axes[2], rows, labels)
    fig.supxlabel(
        "Historical baseline · small generated corpus · one query process / 4 CPUs\n"
        "Client drops count as failed offered work; latency percentiles cover HTTP 200 only.",
        fontsize=10,
    )
    fig.savefig(ROOT / "capacity.png", dpi=180)


if __name__ == "__main__":
    main()
