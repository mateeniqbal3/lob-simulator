"""Liquidity metrics computed from sampled book state (PROJECT.md section 7; ADR-002).

All functions take the snapshot table produced by ``simulation.replay``: one
row per sample time ``t``, holding the book as of ``t``. Every rolling
statistic is trailing (it uses samples in ``(t - window, t]``), so a value
reported at ``t`` never depends on a later sample.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.simulation import N_LEVELS


def add_derived(snapshots: pd.DataFrame, n_levels: int = N_LEVELS) -> pd.DataFrame:
    """Add cumulative depth over the best ``n_levels`` occupied levels per side."""
    df = snapshots.copy()
    for name in ("bid", "ask"):
        cols = [f"{name}_depth_{k}" for k in range(1, n_levels + 1)]
        df[f"{name}_depth_1_{n_levels}"] = df[cols].sum(axis=1)
    return df


def window_mean(df: pd.DataFrame, col: str, start: float, end: float) -> float:
    """Mean of ``col`` over samples with ``start <= t < end`` (NaNs, e.g. an
    undefined spread while one side is empty, are skipped)."""
    mask = (df["t"] >= start) & (df["t"] < end)
    return float(df.loc[mask, col].mean())


def trailing_mean(df: pd.DataFrame, col: str, window: float) -> pd.Series:
    """Mean of ``col`` over samples in ``(t - window, t]`` for each row's ``t``."""
    s = pd.Series(df[col].to_numpy(dtype=float), index=pd.to_timedelta(df["t"], unit="s"))
    rolled = s.rolling(pd.Timedelta(seconds=window), closed="right", min_periods=1).mean()
    return pd.Series(rolled.to_numpy(), index=df.index)


@dataclass(frozen=True)
class Recovery:
    baseline: float
    seconds: float  # time from event end to recovery; nan if censored
    censored: bool


def recovery_time(
    df: pd.DataFrame,
    col: str,
    baseline_window: tuple[float, float],
    event_end: float,
    higher_is_worse: bool,
    tolerance: float = 0.10,
    window: float = 30.0,
) -> Recovery:
    """Resilience per ADR-002.

    Baseline ``B`` is the mean of ``col`` over ``baseline_window``. Recovery is
    the first sample ``t >= event_end`` whose trailing ``window``-second mean is
    within ``tolerance`` of ``B`` on the good side (``<= (1 + tol) B`` if higher
    is worse, e.g. spread; ``>= (1 - tol) B`` otherwise, e.g. depth). If that
    never happens by the last sample the result is censored.
    """
    baseline = window_mean(df, col, *baseline_window)
    trail = trailing_mean(df, col, window)
    after = df["t"] >= event_end
    if higher_is_worse:
        ok = trail <= (1 + tolerance) * baseline
    else:
        ok = trail >= (1 - tolerance) * baseline
    hits = df.loc[after & ok, "t"]
    if hits.empty:
        return Recovery(baseline, np.nan, True)
    return Recovery(baseline, float(hits.iloc[0] - event_end), False)
