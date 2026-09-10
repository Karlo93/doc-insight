"""Render the recorded 100 req/s benchmark without hiding dropped offered work."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent


def main() -> None:
    """Compare delivery, throughput and successful latency for both endpoints."""
    results = json.loads((ROOT / "results.json").read_text())["confirmation"]
    rows = [row for row in results if row["offered_rps"] == 100]
    labels = ["GET /documents", "POST /query"]
    colors = ["#267663", "#b34f32"]
    plt.rcParams.update(
        {"font.size": 11, "axes.spines.top": False, "axes.spines.right": False}
    )
    fig, axes = plt.subplots(1, 3, figsize=(15, 5), constrained_layout=True)
    fig.suptitle("100 offered requests/s · 120 seconds · hosted generation disabled")
    axes[0].bar(labels, [row["completed_rps"] for row in rows], color=colors)
    axes[0].axhline(100, color="#666666", linestyle="--", linewidth=1)
    axes[0].set(
        title="Successful throughput",
        ylabel="Requests/s including drain",
        ylim=(0, 120),
    )
    axes[1].bar(
        labels,
        [row["success_percent"] for row in rows],
        color="#267663",
        label="HTTP 200",
    )
    axes[1].bar(
        labels,
        [100 - row["success_percent"] for row in rows],
        bottom=[row["success_percent"] for row in rows],
        color="#b34f32",
        label="Client dropped",
    )
    axes[1].set(
        title="Delivery of all scheduled work",
        ylabel="Percent of offered requests",
        ylim=(0, 130),
    )
    axes[1].legend(loc="upper right", fontsize=9)
    axes[2].bar(labels, [row["p95_ms"] for row in rows], color=colors)
    axes[2].set(
        title="Successful response latency",
        ylabel="p95 milliseconds (log scale)",
        yscale="log",
        ylim=(1, 40000),
    )
    for index, row in enumerate(rows):
        axes[0].text(
            index, row["completed_rps"] + 3, f"{row['completed_rps']:.2f}", ha="center"
        )
        axes[1].text(
            index, 102, f"{row['statuses']['200']:,} / 12,000", ha="center", fontsize=9
        )
        axes[2].text(
            index,
            row["p95_ms"] * 1.15,
            f"{row['p95_ms']:,.2f} ms",
            ha="center",
            fontsize=9,
        )
    fig.supxlabel(
        "Historical baseline · small generated corpus · one query process / 4 CPUs\nClient drops count as failed offered work; latency percentiles cover HTTP 200 only.",
        fontsize=10,
    )
    fig.savefig(ROOT / "capacity.png", dpi=180)


if __name__ == "__main__":
    main()
