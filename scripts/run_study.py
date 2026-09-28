"""Run the full pre-specified study and write every reported number to results/.

Steps (all parameters come from DECISIONS.md ADR-001, ADR-002 and ADR-008):
  1. for each seed 0-19: simulate the control run and the stressed run for
     every cell of the robustness grid (the primary cell is 5x / 300 s);
  2. summarise spread, depth and recovery per run (src/event_study.py);
  3. run the naive / price-touch / queue-aware comparison on the primary
     stressed event log of each seed (src/naive_fill.py);
  4. write CSV tables, figures and run metadata to results/.

Usage:  python scripts/run_study.py [--workers N] [--seeds N]
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.event_study import (  # noqa: E402
    PRIMARY,
    StudyConfig,
    effects_table,
    mean_paths,
    per_seed_table,
    recovery_table,
    simulate,
    summarize,
)
from src.naive_fill import ProbeConfig, run_comparison  # noqa: E402

RESULTS = ROOT / "results"
FIGURES = RESULTS / "figures"
MULTIPLIERS = (2.0, 5.0, 10.0)
DURATIONS = (60.0, 300.0, 900.0)
PRIMARY_CELL = (5.0, 300.0)
WINDOW_ORDER = ["pre", "event", "early_post", "late_post"]

# Chart colours: stressed run in categorical slot 1, control in a recessive neutral.
C_STRESSED = "#2a78d6"
C_CONTROL = "#8c8c86"
INK, MUTED, GRID, SURFACE = "#1f1f1e", "#6b6b66", "#e6e6e1", "#fcfcfb"


def run_seed(seed: int) -> dict:
    base = StudyConfig()
    _, control_snaps = simulate(base, seed, stressed=False)
    out: dict = {"seed": seed, "grid": [], "control_path": None, "stressed_path": None}
    for mult in MULTIPLIERS:
        for dur in DURATIONS:
            cfg = replace(base, multiplier=mult, event_duration=dur)
            events, snaps = simulate(cfg, seed, stressed=True)
            out["grid"].append({
                "multiplier": mult,
                "duration": dur,
                "stressed": summarize(snaps, cfg),
                "control": summarize(control_snaps, cfg),
            })
            if (mult, dur) == PRIMARY_CELL:
                cols = ["t", *PRIMARY, "ask_depth_1", "mid"]
                out["stressed_path"] = snaps[cols]
                out["control_path"] = control_snaps[cols]
                probes, divergence = run_comparison(events, cfg.horizon, ProbeConfig())
                probes["seed"] = seed
                out["probes"] = probes
                out["divergence"] = {"seed": seed, **divergence}
    return out


def window_of(t: pd.Series, cfg: StudyConfig) -> pd.Series:
    labels = pd.Series(index=t.index, dtype=object)
    for name, (a, b) in cfg.windows().items():
        labels[(t >= a) & (t < b)] = name
    return labels


def fill_summary(probes: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    ok = probes[~probes.skipped.astype(bool)].copy()
    ok["passive_filled"] = ok["passive_filled"].astype(float)
    g = ok.groupby(by)
    out = g.agg(
        probes=("probe_id", "size"),
        fill_rate=("passive_filled", "mean"),
        slippage_vs_posted_ticks=("slippage_vs_posted", "mean"),
        effective_spread_ticks=("effective_spread", "mean"),
        median_time_to_fill_s=("time_to_fill", "median"),
        markout_60s_ticks=("markout", "mean"),
    )
    return out.reset_index()


def style_axes(ax) -> None:
    ax.set_facecolor(SURFACE)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def plot_paths(stressed: pd.DataFrame, control: pd.DataFrame, cfg: StudyConfig, title: str,
               path: Path, smooth: int) -> None:
    panels = [
        ("spread", "Spread (ticks)"),
        ("bid_depth_1", "Best-bid depth (shares)"),
        ("bid_depth_1_5", "Bid depth, best 5 levels (shares)"),
    ]
    fig, axes = plt.subplots(len(panels), 1, figsize=(8, 7.5), sharex=True, facecolor=SURFACE)
    for ax, (col, label) in zip(axes, panels, strict=True):
        style_axes(ax)
        ax.axvspan(cfg.event_start / 60, cfg.event_end / 60, color="#ebebe6", zorder=0)
        for df, color, name in ((control, C_CONTROL, "No-event control"),
                                (stressed, C_STRESSED, "Stressed run")):
            d = df[df.t >= cfg.warmup]
            y = d[col].rolling(smooth, min_periods=1).mean()
            ax.plot(d.t / 60, y, color=color, linewidth=1.6, label=name)
        ax.set_ylabel(label, color=INK, fontsize=9)
    axes[0].text(cfg.event_start / 60 + 0.5, axes[0].get_ylim()[1], "stress event",
                 va="top", fontsize=8, color=MUTED)
    axes[0].legend(frameon=False, fontsize=8, loc="upper right", labelcolor=INK)
    axes[-1].set_xlabel("Simulated time (minutes)", color=INK, fontsize=9)
    fig.suptitle(title, fontsize=10, color=INK, x=0.01, ha="left")
    fig.text(0.01, 0.005, "Synthetic order flow with a designed stress scenario "
             "(DECISIONS.md ADR-002); not a real market event. Before minute 60 the two runs "
             "are identical, so the control line is hidden.", fontsize=7, color=MUTED)
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(path, dpi=130, facecolor=SURFACE)
    plt.close(fig)


def plot_queue_buckets(buckets: pd.DataFrame, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(7, 3.6), facecolor=SURFACE)
    style_axes(ax)
    x = np.arange(len(buckets))
    ax.plot(x, buckets["touch_fill_rate"], color=C_CONTROL, marker="o", markersize=5,
            linewidth=1.6, label="Price-touch (ignores queue)")
    ax.plot(x, buckets["queue_fill_rate"], color=C_STRESSED, marker="o", markersize=5,
            linewidth=1.6, label="Queue-aware engine")
    ax.set_xticks(x, buckets["queue_ahead_bucket"].astype(str), fontsize=8)
    ax.set_ylim(0, 1)
    ax.set_ylabel("Passive fill rate within 60 s", color=INK, fontsize=9)
    ax.set_xlabel("Shares already queued at the probe's price when it was posted",
                  color=INK, fontsize=9)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK)
    fig.text(0.01, 0.005, "Synthetic order flow, primary stress scenario, seeds 0-19.",
             fontsize=7, color=MUTED)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(path, dpi=130, facecolor=SURFACE)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seeds", type=int, default=20)
    args = parser.parse_args()

    cfg = StudyConfig(seeds=tuple(range(args.seeds)))
    RESULTS.mkdir(exist_ok=True)
    FIGURES.mkdir(exist_ok=True)

    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(run_seed, cfg.seeds))

    # --- primary event study -------------------------------------------------------
    primary = []
    for r in results:
        cell = next(g for g in r["grid"] if (g["multiplier"], g["duration"]) == PRIMARY_CELL)
        primary.append({"seed": r["seed"], "stressed": cell["stressed"],
                        "control": cell["control"],
                        "stressed_path": r["stressed_path"], "control_path": r["control_path"]})
    per_seed = per_seed_table(primary)
    per_seed.to_csv(RESULTS / "event_study_per_seed.csv", index=False)
    effects_table(per_seed, cfg).to_csv(RESULTS / "event_study_effects.csv", index=False)
    recovery_table(per_seed).to_csv(RESULTS / "event_study_recovery.csv", index=False)

    plot_paths(mean_paths(primary, "stressed"), mean_paths(primary, "control"), cfg,
               f"Mean across {len(cfg.seeds)} seeds: sell-side market orders x5 for 5 minutes",
               FIGURES / "event_study_seed_mean.png", smooth=10)
    seed0 = next(p for p in primary if p["seed"] == 0)
    plot_paths(seed0["stressed_path"], seed0["control_path"], cfg,
               "Seed 0 (chosen in advance): same scenario, one run, 10 s trailing mean",
               FIGURES / "event_study_seed0.png", smooth=10)

    # --- robustness grid -------------------------------------------------------------
    grid_rows = []
    for mult in MULTIPLIERS:
        for dur in DURATIONS:
            cells = [(r["seed"], g) for r in results for g in r["grid"]
                     if (g["multiplier"], g["duration"]) == (mult, dur)]
            s = pd.DataFrame([g["stressed"] for _, g in cells])
            c = pd.DataFrame([g["control"] for _, g in cells])
            row = {"multiplier": mult, "duration_s": dur,
                   "primary": (mult, dur) == PRIMARY_CELL}
            for m in PRIMARY:
                row[f"{m}_event_diff_median"] = (s[f"{m}__event"] - c[f"{m}__event"]).median()
                row[f"{m}_early_post_diff_median"] = (
                    s[f"{m}__early_post"] - c[f"{m}__early_post"]).median()
                row[f"{m}_recovery_median_s"] = s[f"{m}__recovery_s"].median()
                row[f"{m}_recovery_censored"] = int(s[f"{m}__recovery_censored"].sum())
                row[f"{m}_placebo_median_s"] = c[f"{m}__recovery_s"].median()
            row["one_side_empty_frac_event_median"] = s["one_side_empty_frac__event"].median()
            row["mid_change_event_median"] = s["mid_change__event"].median()
            grid_rows.append(row)
    pd.DataFrame(grid_rows).to_csv(RESULTS / "robustness_grid.csv", index=False)

    # --- naive vs realistic -----------------------------------------------------------
    probes = pd.concat([r["probes"] for r in results], ignore_index=True)
    probes["window"] = window_of(probes["t"], cfg)
    probes["side_name"] = probes["side"].map({1: "buy", -1: "sell"})
    fill_summary(probes, ["assumption"]).to_csv(RESULTS / "fill_comparison_overall.csv",
                                                index=False)
    # Sensitivity: only decisions where both replays posted at the same price.
    posted = probes.pivot_table(index=["seed", "probe_id"], columns="assumption",
                                values="posted", aggfunc="first")
    same = posted[posted["queue"] == posted["touch"]].reset_index()[["seed", "probe_id"]]
    fill_summary(probes.merge(same, on=["seed", "probe_id"]), ["assumption"]).to_csv(
        RESULTS / "fill_comparison_overall_same_posted.csv", index=False)
    by_window = fill_summary(probes, ["assumption", "window", "side_name"])
    by_window["window"] = pd.Categorical(by_window["window"], WINDOW_ORDER, ordered=True)
    by_window.sort_values(["assumption", "side_name", "window"]).to_csv(
        RESULTS / "fill_comparison_by_window_side.csv", index=False)

    q = probes[(probes.assumption == "queue") & ~probes.skipped.astype(bool)]
    t = probes[(probes.assumption == "touch") & ~probes.skipped.astype(bool)]
    qt = q.merge(t[["seed", "probe_id", "passive_filled"]], on=["seed", "probe_id"],
                 suffixes=("_queue", "_touch"))
    bins = [0, 200, 500, 1000, 2000, np.inf]
    labels = ["<200", "200-499", "500-999", "1000-1999", "2000+"]
    qt["queue_ahead_bucket"] = pd.cut(qt["queue_ahead"], bins, right=False, labels=labels)
    buckets = qt.groupby("queue_ahead_bucket", observed=False).agg(
        probes=("probe_id", "size"),
        touch_fill_rate=("passive_filled_touch", lambda s: s.astype(float).mean()),
        queue_fill_rate=("passive_filled_queue", lambda s: s.astype(float).mean()),
    ).reset_index()
    buckets.to_csv(RESULTS / "fill_comparison_queue_buckets.csv", index=False)
    plot_queue_buckets(buckets, FIGURES / "fill_rate_by_queue_ahead.png")

    touch_only = qt[qt.passive_filled_touch.astype(bool) & ~qt.passive_filled_queue.astype(bool)]
    mech = {
        "probes_touch_filled_but_queue_not": int(len(touch_only)),
        "share_of_touch_fills_lost_to_queue": float(
            len(touch_only) / qt.passive_filled_touch.astype(bool).sum()),
        "median_queue_ahead_touch_only": float(touch_only.queue_ahead.median()),
        "median_queue_ahead_queue_filled": float(
            qt[qt.passive_filled_queue.astype(bool)].queue_ahead.median()),
        "median_queue_ahead_all": float(qt.queue_ahead.median()),
        "queue_probes_with_cleanup_unfilled": int((q.unfilled_after_cleanup > 0).sum()),
        "skipped_probe_decisions": int(probes[probes.assumption == "queue"].skipped.sum()),
    }
    divergence = pd.DataFrame([r["divergence"] for r in results])
    divergence.to_csv(RESULTS / "fill_comparison_background_divergence.csv", index=False)
    mech["background_fills_not_reproduced_share"] = float(
        divergence.background_fills_not_reproduced.sum() / divergence.background_fills.sum())
    mech["quote_samples_differing_frac_mean"] = float(
        divergence.quote_samples_differing_frac.mean())
    mech["probes_posted_differently"] = int(divergence.probes_posted_differently.sum())
    mech["probe_decisions"] = int(divergence.probes.sum())
    mech["median_own_queue_ahead"] = float(q.own_queue_ahead.median())
    mech["mean_own_share_of_queue_ahead"] = float(
        q.own_queue_ahead.sum() / q.queue_ahead.sum())
    (RESULTS / "fill_comparison_mechanism.json").write_text(json.dumps(mech, indent=2) + "\n")

    processed = ROOT / "data" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    probes.to_csv(processed / "probes_all.csv.gz", index=False)

    meta = {
        "seeds": list(cfg.seeds),
        "study_config": {k: (v.name if hasattr(v, "name") else v)
                         for k, v in asdict(cfg).items() if k not in ("params", "seeds")},
        "order_flow_params": asdict(cfg.params),
        "probe_config": asdict(ProbeConfig()),
        "robustness_grid": {"multipliers": MULTIPLIERS, "durations_s": DURATIONS},
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "matplotlib": matplotlib.__version__,
    }
    (RESULTS / "run_metadata.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"Wrote results for {len(cfg.seeds)} seeds to {RESULTS}")


if __name__ == "__main__":
    main()
