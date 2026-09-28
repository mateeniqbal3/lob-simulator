"""The order-flow generator produces the documented statistical properties (ADR-001)."""

from __future__ import annotations

import numpy as np
import pytest

from src.event_injection import StressScenario
from src.events import Cancel, LimitOrder, MarketOrder, Side
from src.matching_engine import MatchingEngine
from src.order_flow import OrderFlowParams, generate_order_flow

P = OrderFlowParams()
HORIZON = 3000.0


@pytest.fixture(scope="module")
def flow():
    return generate_order_flow(P, HORIZON, seed=123)


def test_deterministic_given_seed(flow):
    assert generate_order_flow(P, HORIZON, seed=123) == flow
    assert generate_order_flow(P, HORIZON, seed=124) != flow


def test_timestamps_increasing_and_within_horizon(flow):
    ts = np.array([e.ts for e in flow])
    assert np.all(np.diff(ts) > 0) and ts[0] > 0 and ts[-1] <= HORIZON


def test_arrival_rates_match_parameters(flow):
    for side in (Side.BUY, Side.SELL):
        n_lim = sum(isinstance(e, LimitOrder) and e.side is side for e in flow)
        n_mkt = sum(isinstance(e, MarketOrder) and e.side is side for e in flow)
        # Poisson counts: allow ~4 standard deviations.
        assert abs(n_lim - P.limit_rate * HORIZON) < 4 * np.sqrt(P.limit_rate * HORIZON)
        assert abs(n_mkt - P.market_rate * HORIZON) < 4 * np.sqrt(P.market_rate * HORIZON)


def test_cancellation_rate_per_resting_order(flow):
    """Cancels / (time-integral of the number of resting orders) estimates cancel_rate."""
    eng = MatchingEngine()
    exposure, last_t, n_cancel = 0.0, 0.0, 0
    for ev in flow:
        exposure += len(eng.book) * (ev.ts - last_t)
        last_t = ev.ts
        res = eng.process(ev)
        if isinstance(ev, Cancel):
            assert res.accepted  # the generator only cancels orders that are resting
            n_cancel += 1
    est = n_cancel / exposure
    assert abs(est - P.cancel_rate) < 4 * np.sqrt(n_cancel) / exposure


def test_limit_placement_distribution_and_never_marketable(flow):
    eng = MatchingEngine()
    dists = []
    for ev in flow:
        if isinstance(ev, LimitOrder):
            ref = eng.book.best_ask() if ev.side is Side.BUY else eng.book.best_bid()
            res = eng.process(ev)
            assert res.fills == ()  # limit orders never cross in this model
            if ref is not None:
                dists.append(ref - ev.price if ev.side is Side.BUY else ev.price - ref)
        else:
            eng.process(ev)
    counts = np.bincount(dists, minlength=P.max_distance + 1)[1:]
    assert min(dists) >= 1 and max(dists) <= P.max_distance
    expected = P.distance_probs() * len(dists)
    assert np.all(np.abs(counts - expected) < 5 * np.sqrt(expected))


def test_order_sizes(flow):
    lim_sizes = np.array([e.qty for e in flow if isinstance(e, LimitOrder)])
    mkt_sizes = np.array([e.qty for e in flow if isinstance(e, MarketOrder)])
    assert np.all(lim_sizes % P.lot == 0) and np.all(mkt_sizes % P.lot == 0)
    assert lim_sizes.min() == P.lot and lim_sizes.max() == P.lot * P.limit_max_lots
    assert abs(lim_sizes.mean() - P.lot * (1 + P.limit_max_lots) / 2) < 15
    assert abs(mkt_sizes.mean() - P.lot / P.market_size_p) < 25


def test_stress_scenario_multiplies_only_the_targeted_rate():
    sc = StressScenario(start=1000.0, duration=1000.0, side=Side.SELL, market_multiplier=5.0)
    flow = generate_order_flow(P, HORIZON, seed=5, schedule=sc)

    def count(kind, side, a, b):
        return sum(isinstance(e, kind) and e.side is side and a <= e.ts < b for e in flow)

    during_sell = count(MarketOrder, Side.SELL, 1000, 2000)
    during_buy = count(MarketOrder, Side.BUY, 1000, 2000)
    expected = 5 * P.market_rate * 1000
    assert abs(during_sell - expected) < 4 * np.sqrt(expected)
    assert abs(during_buy - P.market_rate * 1000) < 4 * np.sqrt(P.market_rate * 1000)
    outside = count(MarketOrder, Side.SELL, 0, 1000) + count(MarketOrder, Side.SELL, 2000, 3000)
    assert abs(outside - P.market_rate * 2000) < 4 * np.sqrt(P.market_rate * 2000)
    lim_during = count(LimitOrder, Side.BUY, 1000, 2000)
    assert abs(lim_during - P.limit_rate * 1000) < 4 * np.sqrt(P.limit_rate * 1000)


def test_future_schedule_cannot_change_the_past():
    """Generator-level no-look-ahead: an event starting at T leaves every event before T
    identical, whatever the scenario does after T."""
    base = generate_order_flow(P, HORIZON, seed=11)
    for sc in (
        StressScenario(1500.0, 300.0, Side.SELL, 5.0),
        StressScenario(1500.0, 900.0, Side.BUY, 10.0),
    ):
        stressed = generate_order_flow(P, HORIZON, seed=11, schedule=sc)
        before = [e for e in base if e.ts < 1500.0]
        assert [e for e in stressed if e.ts < 1500.0] == before
        assert stressed != base
