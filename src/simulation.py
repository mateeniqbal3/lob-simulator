"""Replay an event log through a fresh matching engine and record book state over time.

Sampling is "as of" each grid time ``t``: a snapshot at ``t`` reflects every
event with ``ts <= t`` and nothing later. The replay loop only ever holds the
current event, so a snapshot cannot depend on a future event; this is checked
directly in tests/test_simulation.py by comparing against truncated streams.

Optional *agents* (used by ``naive_fill.py``) are called at their own
decision times with the engine as of that time (after all background events
with ``ts <= t``) and may submit orders, which are processed immediately with
timestamp ``t``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import pandas as pd

from src.events import Event, Side
from src.matching_engine import MatchingEngine

N_LEVELS = 5


class Agent(Protocol):
    def next_time(self) -> float | None: ...

    def act(self, t: float, engine: MatchingEngine) -> list[Event]: ...


@dataclass
class ReplayResult:
    engine: MatchingEngine
    snapshots: pd.DataFrame  # one row per sample time


def snapshot_row(eng: MatchingEngine, t: float, n_levels: int = N_LEVELS) -> dict:
    book = eng.book
    bid, ask = book.best_bid(), book.best_ask()
    row = {
        "t": t,
        "bid": np.nan if bid is None else bid,
        "ask": np.nan if ask is None else ask,
    }
    row["spread"] = row["ask"] - row["bid"]
    row["mid"] = (row["ask"] + row["bid"]) / 2
    for side, name in ((Side.BUY, "bid"), (Side.SELL, "ask")):
        for k in range(1, n_levels + 1):
            row[f"{name}_depth_{k}"] = book.depth_at_level(side, k)
    return row


def replay(
    events: list[Event],
    horizon: float,
    sample_interval: float = 1.0,
    agents: list[Agent] | None = None,
    n_levels: int = N_LEVELS,
) -> ReplayResult:
    eng = MatchingEngine()
    agents = agents or []
    rows: list[dict] = []
    next_sample = 0.0

    def advance_to(ts: float, inclusive: bool) -> None:
        """Run samples and agent actions scheduled before ``ts`` (or at ``ts``)."""
        nonlocal next_sample
        while True:
            agent_times = [(a.next_time(), i) for i, a in enumerate(agents)]
            agent_times = [(tt, i) for tt, i in agent_times if tt is not None]
            t_agent, i_agent = min(agent_times) if agent_times else (np.inf, -1)
            t_next = min(next_sample, t_agent)
            if t_next > horizon or t_next > ts or (t_next == ts and not inclusive):
                return
            if next_sample <= t_agent:
                rows.append(snapshot_row(eng, next_sample, n_levels))
                next_sample += sample_interval
            else:
                for ev in agents[i_agent].act(t_agent, eng):
                    eng.process(ev)

    for ev in events:
        # Samples / agent decisions strictly before this event see state as of then;
        # those at exactly ev.ts must wait until every event with that ts is processed,
        # which is handled because the next event's call runs them (inclusive=False).
        advance_to(ev.ts, inclusive=False)
        eng.process(ev)
    advance_to(horizon, inclusive=True)
    return ReplayResult(eng, pd.DataFrame(rows))
