"""Generate the figures used in paper/writeup.md and the README.

Reads only committed outputs in results/. It does not rerun the simulation
or change any recorded result.

- fig1: results/figures/event_study_seed_mean.png with its footnote strip
  cropped off (the paper caption carries the same caveat).
- fig2, fig3 and the README chart: drawn from the fill-comparison CSVs.

Usage (from the repository root):
    python paper/make_figures.py
"""

from pathlib import Path

import matplotlib
import pandas as pd
from PIL import Image

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results"
OUT = ROOT / "paper" / "figures"
OUT.mkdir(parents=True, exist_ok=True)

NAIVE_C, TOUCH_C, QUEUE_C, INK = "#8C8C8C", "#DD8452", "#4C72B0", "#333333"
LABELS = {
    "naive": "Naive\n(instant fill)",
    "touch": "Price-touch\n(ignores queue)",
    "queue": "Queue-aware\n(real engine)",
}
COLORS = {"naive": NAIVE_C, "touch": TOUCH_C, "queue": QUEUE_C}
ORDER = ["naive", "touch", "queue"]

plt.rcParams.update(
    {
        "font.size": 10,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.alpha": 0.3,
        "savefig.dpi": 200,
        "savefig.bbox": "tight",
    }
)

overall = pd.read_csv(RES / "fill_comparison_overall.csv").set_index("assumption")
buckets = pd.read_csv(RES / "fill_comparison_queue_buckets.csv")


def effective_spread(ax):
    """Effective spread per probe under each fill assumption, with the two-step decomposition."""
    es = overall["effective_spread_ticks"]
    x = range(len(ORDER))
    vals = [es[a] for a in ORDER]
    ax.bar(x, vals, width=0.5, color=[COLORS[a] for a in ORDER])
    for i, v in enumerate(vals):
        ax.text(
            i,
            v + (0.06 if v >= 0 else -0.06),
            f"{v:+.2f}",
            ha="center",
            va="bottom" if v >= 0 else "top",
            fontsize=9,
            fontweight="bold",
            color=INK,
        )
    ax.axhline(0, color="black", lw=0.8)
    steps = [
        (0, 1, es["touch"] - es["naive"], "price never\nreaches order"),
        (1, 2, es["queue"] - es["touch"], "queue ahead\nnot cleared"),
    ]
    for a, b, d, text in steps:
        ax.annotate(
            "",
            xy=(b - 0.32, vals[b]),
            xytext=(a + 0.32, vals[a]),
            arrowprops={"arrowstyle": "->", "color": "#666666", "lw": 1},
        )
        ax.text(
            (a + b) / 2,
            (-0.32 if a == 0 else 0.62),
            f"{d:+.2f}\n{text}",
            ha="center",
            fontsize=8,
            color="#555555",
        )
    ax.set_xticks(list(x), [LABELS[a] for a in ORDER])
    ax.set_ylabel("Effective spread paid per probe (ticks)\nnegative = spread earned")
    ax.set_ylim(-1.75, 0.95)
    ax.set_title(
        "Same 14,257 passive orders, same background flow:\n"
        "the naive assumption earns 1.40 ticks, the real queue pays 0.26"
    )
    ax.grid(axis="x", visible=False)


def fill_rate_by_queue(ax):
    """Fill rate within 60 s by shares queued ahead at posting, price-touch vs queue-aware."""
    xs = range(len(buckets))
    ax.plot(
        xs,
        buckets["touch_fill_rate"] * 100,
        "-o",
        color=TOUCH_C,
        lw=1.8,
        ms=6,
        label="Price-touch (ignores queue)",
    )
    ax.plot(
        xs,
        buckets["queue_fill_rate"] * 100,
        "-o",
        color=QUEUE_C,
        lw=1.8,
        ms=6,
        label="Queue-aware engine",
    )
    for i, (t, q) in enumerate(
        zip(buckets["touch_fill_rate"], buckets["queue_fill_rate"], strict=True)
    ):
        ax.text(i, q * 100 - 1.6, f"{q:.0%}", ha="center", va="top", fontsize=8, color=QUEUE_C)
        if i in (0, len(buckets) - 1):
            ax.text(
                i, t * 100 + 1.0, f"{t:.0%}", ha="center", va="bottom", fontsize=8, color=TOUCH_C
            )
    ax.set_xticks(
        list(xs),
        [
            f"{b}\n(n={n:,})"
            for b, n in zip(buckets["queue_ahead_bucket"], buckets["probes"], strict=True)
        ],
    )
    ax.set_xlabel("Shares already queued at the probe's price when it was posted")
    ax.set_ylabel("Fill rate within 60 s (%)")
    ax.set_ylim(70, 102)
    ax.legend(frameon=False, loc="lower left", fontsize=9)
    ax.set_title("Fills fall with queue position only when the queue is modelled")


# Figure 1: event-study chart from the study run, footnote strip cropped.
src = Image.open(RES / "figures" / "event_study_seed_mean.png")
src.crop((0, 0, src.width, 945)).save(OUT / "fig1_event_study.png")

# Figure 2: effective spread under the three fill assumptions.
fig, ax = plt.subplots(figsize=(6.0, 4.3))
effective_spread(ax)
fig.savefig(OUT / "fig2_effective_spread.png")
plt.close(fig)

# Figure 3: fill rate by queue ahead.
fig, ax = plt.subplots(figsize=(6.2, 3.9))
fill_rate_by_queue(ax)
fig.savefig(OUT / "fig3_fill_rate_by_queue.png")
plt.close(fig)

# README hero: figures 2 and 3 side by side.
fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.6))
effective_spread(axes[0])
fill_rate_by_queue(axes[1])
fig.suptitle(
    "Synthetic limit order book: ignoring the queue turns a 0.26-tick cost into a 1.40-tick profit",
    fontweight="bold",
)
fig.tight_layout()
fig.savefig(OUT / "readme_hero.png")
plt.close(fig)

print(f"Wrote figures to {OUT.relative_to(ROOT)}")
