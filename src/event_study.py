"""Before / during / after liquidity event study (PROJECT.md sections 3 and 7; ADR-002).

Every seed is simulated twice with the same random seed: once with the
stress scenario injected and once without (control). Because the scenario
only changes rates from ``event_start`` onward and the generator restarts its
clock at that breakpoint, the two runs are identical before the event, and
stressed-minus-control differences isolate the event's effect from the
seed's own noise.

This is a controlled experiment on synthetic order flow. Its results describe
the behaviour of this model under a designed stress scenario, not any real
market.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.event_injection import StressScenario
from src.events import Event, Side
from src.metrics import add_derived, recovery_time, window_mean
from src.order_flow import OrderFlowParams, generate_order_flow
from src.simulation import replay

# metric -> True if a higher value means worse liquidity, False if lower is worse,
# None if no direction is predicted (secondary, descriptive metrics).
METRICS: dict[str, bool | None] = {
    "spread": True,
    "bid_depth_1": False,
    "bid_depth_1_5": False,
    "ask_depth_1": None,
    "ask_depth_1_5": None,
}
PRIMARY = ("spread", "bid_depth_1", "bid_depth_1_5")


@dataclass(frozen=True)
class StudyConfig:
    params: OrderFlowParams = field(default_factory=OrderFlowParams)
    horizon: float = 7200.0
    warmup: float = 1800.0
    event_start: float = 3600.0
    event_duration: float = 300.0
    multiplier: float = 5.0
    side: Side = Side.SELL
    seeds: tuple[int, ...] = tuple(range(20))
    early_post: float = 300.0
    recovery_tolerance: float = 0.10
    recovery_window: float = 30.0

    @property
    def event_end(self) -> float:
        return self.event_start + self.event_duration

    def scenario(self) -> StressScenario:
        return StressScenario(self.event_start, self.event_duration, self.side, self.multiplier)

    def windows(self) -> dict[str, tuple[float, float]]:
        end = self.event_end
        return {
            "pre": (self.warmup, self.event_start),
            "event": (self.event_start, end),
            "early_post": (end, end + self.early_post),
            "late_post": (end + self.early_post, self.horizon + 1),
        }


def simulate(cfg: StudyConfig, seed: int, stressed: bool) -> tuple[list[Event], pd.DataFrame]:
    schedule = cfg.scenario() if stressed else None
    events = generate_order_flow(cfg.params, cfg.horizon, seed, schedule)
    snaps = add_derived(replay(events, cfg.horizon).snapshots)
    return events, snaps


def summarize(snaps: pd.DataFrame, cfg: StudyConfig) -> dict[str, float]:
    out: dict[str, float] = {}
    for metric in METRICS:
        for name, (a, b) in cfg.windows().items():
            out[f"{metric}__{name}"] = window_mean(snaps, metric, a, b)
    for metric in PRIMARY:
        rec = recovery_time(
            snaps,
            metric,
            cfg.windows()["pre"],
            cfg.event_end,
            higher_is_worse=METRICS[metric],
            tolerance=cfg.recovery_tolerance,
            window=cfg.recovery_window,
        )
        out[f"{metric}__recovery_s"] = rec.seconds
        out[f"{metric}__recovery_censored"] = float(rec.censored)
    ev = (snaps["t"] >= cfg.event_start) & (snaps["t"] < cfg.event_end)
    out["one_side_empty_frac__event"] = float(snaps.loc[ev, "spread"].isna().mean())
    out["mid_change__event"] = float(
        snaps.loc[snaps["t"] < cfg.event_end, "mid"].iloc[-1]
        - snaps.loc[snaps["t"] < cfg.event_start, "mid"].iloc[-1]
    )
    return out


def run_seed(cfg: StudyConfig, seed: int, arms=("stressed", "control")) -> dict:
    """Run one seed; returns summaries, sampled paths and the stressed event log."""
    result: dict = {"seed": seed}
    for arm in arms:
        events, snaps = simulate(cfg, seed, stressed=(arm == "stressed"))
        result[arm] = summarize(snaps, cfg)
        result[f"{arm}_path"] = snaps[["t", *PRIMARY, "ask_depth_1", "mid"]]
        if arm == "stressed":
            result["stressed_events"] = events
    return result


def per_seed_table(results: list[dict]) -> pd.DataFrame:
    rows = []
    for r in results:
        for arm in ("stressed", "control"):
            if arm in r:
                rows.append({"seed": r["seed"], "arm": arm, **r[arm]})
    return pd.DataFrame(rows)


def effects_table(per_seed: pd.DataFrame, cfg: StudyConfig) -> pd.DataFrame:
    """Per metric and window: control and stressed medians, and the median,
    IQR and sign count of the per-seed (stressed - control) difference."""
    s = per_seed[per_seed.arm == "stressed"].set_index("seed").sort_index()
    c = per_seed[per_seed.arm == "control"].set_index("seed").sort_index()
    rows = []
    for metric, worse_up in METRICS.items():
        for window in cfg.windows():
            col = f"{metric}__{window}"
            diff = s[col] - c[col]
            if worse_up is None:
                n_pred = np.nan
            else:
                n_pred = int(((diff > 0) if worse_up else (diff < 0)).sum())
            rows.append({
                "metric": metric,
                "window": window,
                "control_median": c[col].median(),
                "stressed_median": s[col].median(),
                "diff_median": diff.median(),
                "diff_q25": diff.quantile(0.25),
                "diff_q75": diff.quantile(0.75),
                "seeds_predicted_sign": n_pred,
                "seeds": len(diff),
            })
    return pd.DataFrame(rows)


def recovery_table(per_seed: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for metric in PRIMARY:
        for arm, label in (("stressed", "after event"), ("control", "placebo (no event)")):
            d = per_seed[per_seed.arm == arm]
            secs = d[f"{metric}__recovery_s"]
            rows.append({
                "metric": metric,
                "arm": label,
                "median_s": secs.median(),
                "q25_s": secs.quantile(0.25),
                "q75_s": secs.quantile(0.75),
                "max_s": secs.max(),
                "censored": int(d[f"{metric}__recovery_censored"].sum()),
                "seeds": len(d),
            })
    return pd.DataFrame(rows)


def mean_paths(results: list[dict], arm: str) -> pd.DataFrame:
    """Cross-seed mean of each sampled metric at every sample time."""
    paths = [r[f"{arm}_path"].set_index("t") for r in results if f"{arm}_path" in r]
    return pd.concat(paths).groupby(level=0).mean().reset_index()
