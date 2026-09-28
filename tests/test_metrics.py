"""Liquidity metrics on hand-built series with known answers."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.metrics import add_derived, recovery_time, trailing_mean, window_mean


def frame(values: dict[str, list[float]]) -> pd.DataFrame:
    n = len(next(iter(values.values())))
    return pd.DataFrame({"t": np.arange(n, dtype=float), **values})


def test_add_derived_sums_levels():
    df = pd.DataFrame({"t": [0.0], **{f"bid_depth_{k}": [k] for k in range(1, 6)},
                       **{f"ask_depth_{k}": [10 * k] for k in range(1, 6)}})
    out = add_derived(df)
    assert out.loc[0, "bid_depth_1_5"] == 15 and out.loc[0, "ask_depth_1_5"] == 150


def test_window_mean_half_open_and_skips_nan():
    df = frame({"x": [1, 2, np.nan, 4, 5]})
    assert window_mean(df, "x", 1, 4) == 3.0  # samples t=1,2,3 -> (2 + 4) / 2
    assert window_mean(df, "x", 0, 1) == 1.0


def test_trailing_mean_is_causal():
    df = frame({"x": [1.0] * 10 + [100.0] * 10})
    tm = trailing_mean(df, "x", window=3.0)
    assert tm.iloc[9] == 1.0  # (6, 9] contains only the 1.0 samples
    assert tm.iloc[10] == (1 + 1 + 100) / 3
    df2 = df.copy()
    df2.loc[df2.t > 12, "x"] = -5.0  # change the future only
    tm2 = trailing_mean(df2, "x", window=3.0)
    pd.testing.assert_series_equal(tm.iloc[:13], tm2.iloc[:13])


def test_spread_recovery_time():
    # baseline 1 on t in [0, 50); shock to 5 on [50, 60); decays to 1 by t=70.
    x = [1.0] * 50 + [5.0] * 10 + list(np.linspace(5, 1, 11))[1:] + [1.0] * 30
    df = frame({"spread": x})
    rec = recovery_time(df, "spread", (0, 50), event_end=60, higher_is_worse=True,
                        tolerance=0.10, window=5.0)
    tm = trailing_mean(df, "spread", 5.0)
    first = df.t[(df.t >= 60) & (tm <= 1.1)].iloc[0]
    assert rec.baseline == 1.0 and not rec.censored
    assert rec.seconds == first - 60
    assert 10 <= rec.seconds <= 15  # values reach 1.0 at t=70, window mean needs a few samples


def test_depth_recovery_and_censoring():
    x = [100.0] * 50 + [10.0] * 30 + [95.0] * 20
    df = frame({"depth": x})
    rec = recovery_time(df, "depth", (0, 50), event_end=60, higher_is_worse=False,
                        tolerance=0.10, window=1.0)
    assert rec.seconds == 20.0  # t=80 is the first sample back at >= 90
    never = frame({"depth": [100.0] * 50 + [10.0] * 50})
    rec2 = recovery_time(never, "depth", (0, 50), event_end=60, higher_is_worse=False)
    assert rec2.censored and np.isnan(rec2.seconds)
