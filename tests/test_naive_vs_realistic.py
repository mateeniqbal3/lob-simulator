"""The three fill assumptions on small, hand-built event logs with known outcomes."""

from __future__ import annotations

import numpy as np
import pytest

from src.events import Side
from src.naive_fill import ProbeConfig, run_comparison
from src.order_flow import OrderFlowParams, generate_order_flow
from tests._util import lim, mkt

CFG = ProbeConfig(start=10.0, end=10.0, interval=15.0, size=100, max_wait=60.0)
BUY, SELL = Side.BUY.value, Side.SELL.value


def rows(df, assumption, side):
    r = df[(df.assumption == assumption) & (df.side == side)]
    assert len(r) == 1
    return r.iloc[0]


def test_touch_fills_but_queue_does_not_when_trade_is_smaller_than_queue_ahead():
    events = [
        lim(0.0, 1, Side.BUY, 100, 500),
        lim(0.0, 2, Side.SELL, 101, 500),
        mkt(20.0, 3, Side.SELL, 200),  # prints at 100, but 500 shares are ahead of the probe
    ]
    df, div = run_comparison(events, horizon=100.0, config=CFG)

    naive = rows(df, "naive", BUY)
    assert naive.passive_filled and naive.exec_price == 100 and naive.slippage_vs_posted == 0
    assert naive.effective_spread == 2 * (100 - 100.5)

    touch = rows(df, "touch", BUY)
    assert touch.passive_filled and touch.time_to_fill == 10.0 and touch.exec_price == 100

    queue = rows(df, "queue", BUY)
    assert not queue.passive_filled and queue.queue_ahead == 500
    assert queue.exec_price == 101  # cleanup market buy at the ask after 60 s
    assert queue.slippage_vs_posted == 1 and queue.effective_spread == 2 * (101 - 100.5)

    # Sell probe at 101: nothing ever trades there, so both touch and queue clean up at the bid.
    for a in ("touch", "queue"):
        r = rows(df, a, SELL)
        assert not r.passive_filled and r.exec_price == 100 and r.slippage_vs_posted == 1
    assert div["background_fills_not_reproduced"] == 0


def test_queue_probe_fills_once_the_queue_ahead_is_consumed():
    events = [
        lim(0.0, 1, Side.BUY, 100, 500),
        lim(0.0, 2, Side.SELL, 101, 500),
        mkt(20.0, 3, Side.SELL, 600),
    ]
    df, div = run_comparison(events, horizon=100.0, config=CFG)
    queue = rows(df, "queue", BUY)
    assert queue.passive_filled and queue.exec_price == 100 and queue.time_to_fill == 10.0
    assert queue.passive_qty == 100
    # The 100 shares that expired in the no-probe run hit the probe instead.
    assert div["background_fills_not_reproduced"] == 0


def test_empty_side_probe_is_skipped():
    events = [lim(0.0, 1, Side.BUY, 100, 500)]
    df, _ = run_comparison(events, horizon=100.0, config=CFG)
    sells = df[df.skipped]
    assert len(sells) == 3  # the sell probe under all three assumptions
    assert not df[~df.skipped].empty


@pytest.fixture(scope="module")
def synthetic_comparison():
    flow = generate_order_flow(OrderFlowParams(), 1200.0, seed=21)
    cfg = ProbeConfig(start=300.0, end=1100.0, interval=15.0, size=100, max_wait=60.0)
    return run_comparison(flow, 1200.0, cfg)


def test_naive_is_an_upper_bound_on_realistic_fill_rate(synthetic_comparison):
    df, div = synthetic_comparison
    ok = df[~df.skipped]
    rate = ok.groupby("assumption").passive_filled.mean()
    assert rate["naive"] == 1.0
    assert rate["queue"] <= rate["touch"] <= rate["naive"]
    slip = ok.groupby("assumption").slippage_vs_posted.mean()
    assert slip["naive"] == 0.0 and slip["queue"] >= 0.0
    assert div["probes"] == ok.probe_id.nunique() + df[df.skipped].probe_id.nunique()


def test_queue_filled_probes_trade_exactly_at_posted_price(synthetic_comparison):
    df, _ = synthetic_comparison
    q = df[(df.assumption == "queue") & (~df.skipped) & (df.passive_filled.astype(bool))]
    assert len(q) > 0
    assert np.all(q.exec_price == q.posted)
