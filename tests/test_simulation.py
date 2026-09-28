"""Simulation-level no-look-ahead: a snapshot "as of T" uses only events with ts <= T."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.events import Side
from src.order_flow import OrderFlowParams, generate_order_flow
from src.simulation import replay, snapshot_row
from tests._util import lim, mkt

HORIZON = 600.0


@pytest.fixture(scope="module")
def flow():
    return generate_order_flow(OrderFlowParams(), HORIZON, seed=3)


def test_snapshot_equals_replay_of_truncated_stream(flow):
    full = replay(flow, HORIZON, sample_interval=1.0).snapshots.set_index("t")
    for t in (0.0, 1.0, 37.0, 250.0, 599.0, 600.0):
        truncated = replay([e for e in flow if e.ts <= t], t, sample_interval=1.0).snapshots
        row = truncated.set_index("t").loc[t]
        pd.testing.assert_series_equal(full.loc[t], row, check_names=False)


def test_future_events_do_not_change_past_snapshots(flow):
    full = replay(flow, HORIZON).snapshots
    cut = 300.0
    altered = [e for e in flow if e.ts <= cut]  # drop the entire future
    past = replay(altered, HORIZON).snapshots
    pd.testing.assert_frame_equal(full[full.t <= cut], past[past.t <= cut])
    assert not full[full.t > cut].equals(past[past.t > cut])


def test_events_at_exactly_sample_time_are_included():
    events = [lim(0.5, 1, Side.BUY, 100, 10), lim(2.0, 2, Side.SELL, 101, 10),
              mkt(2.0, 3, Side.BUY, 10)]
    snaps = replay(events, 3.0).snapshots.set_index("t")
    assert np.isnan(snaps.loc[0.0, "bid"]) and snaps.loc[1.0, "bid"] == 100
    # at t=2.0 both events with ts=2.0 have been applied: ask placed then taken.
    assert np.isnan(snaps.loc[2.0, "ask"])


def test_replay_reproduces_generator_state(flow):
    """The generator only ever cancels resting orders, so any divergence between its
    internal book and the replayed book would surface as a rejected cancel."""
    eng = replay(flow, HORIZON).engine
    assert eng.rejected_cancels == 0
    eng.check_invariants()


def test_agent_sees_state_as_of_its_decision_time(flow):
    seen = {}

    class Recorder:
        times = [10.0, 123.0, 450.0]

        def next_time(self):
            return self.times[0] if self.times else None

        def act(self, t, engine):
            self.times.pop(0)
            seen[t] = snapshot_row(engine, t)
            return []

    replay(flow, HORIZON, agents=[Recorder()])
    for t, row in seen.items():
        truncated = replay([e for e in flow if e.ts <= t], t).snapshots.set_index("t").loc[t]
        assert row["bid"] == truncated["bid"] and row["ask"] == truncated["ask"]
        assert row["bid_depth_1"] == truncated["bid_depth_1"]
