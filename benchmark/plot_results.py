"""Render committed benchmark summaries; run with matplotlib 3.10.7."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent


def main() -> None:
    rows = json.loads((ROOT / "results.json").read_text())["confirmation"]
    labels = [f"{r['mode']}\n{r['offered_rps']} offered RPS" for r in rows]
    plt.rcParams.update(
        {"font.size": 11, "axes.spines.top": False, "axes.spines.right": False}
    )
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), constrained_layout=True)
    colors = ["#29806c" if r["success_percent"] == 100 else "#b85436" for r in rows]
    axes[0].bar(labels, [r["completed_rps"] for r in rows], color=colors)
    axes[0].set(
        ylabel="Successful requests / second (including drain)",
        title="Single-server throughput · 120-second stages",
    )
    for index, row in enumerate(rows):
        axes[0].text(
            index,
            row["completed_rps"] + 2,
            f"{row['success_percent']:g}% delivered",
            ha="center",
            fontsize=9,
        )
    axes[1].bar(labels, [r["p95_ms"] for r in rows], color=colors)
    axes[1].set(
        yscale="log",
        ylabel="p95 successful latency, ms (log scale)",
        title="Queueing dominates overloaded queries",
    )
    for index, row in enumerate(rows):
        axes[1].text(
            index,
            row["p95_ms"] * 1.12,
            f"{row['p95_ms']:,.1f} ms",
            ha="center",
            fontsize=9,
        )
    axes[1].set_ylim(1, 40000)
    fig.savefig(ROOT / "capacity.png", dpi=180)


if __name__ == "__main__":
    main()
