"""Naive vs. queue-aware execution on identical order flow (PROJECT.md section 9; ADR-008).

Small passive "probe" orders are posted at the best quote on a fixed schedule
and judged under three fill assumptions:

1. ``naive``: fills instantly and in full at the posted price (the spec's
   naive assumption).
2. ``touch``: fills in full at the posted price the first time a background
   trade prints at or through that price within ``max_wait``; ignores queue
   position. Otherwise cleanup at the opposite best quote at the deadline.
3. ``queue``: the probe is actually inserted into the matching engine, at
   the back of its price level's queue, and fills only through price-time
   priority. Anything unfilled at the deadline is cancelled and completed
   with a real market order.

``naive`` and ``touch`` are evaluated on a replay of the background event log
with no probes in it; ``queue`` replays exactly the same log with the probes
inserted. ``background_divergence`` measures how much the probes' presence
changed what happened to background orders.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.events import Cancel, Event, LimitOrder, MarketOrder, Side
from src.matching_engine import MatchingEngine
from src.simulation import replay

PROBE_ID_BASE = 1_000_000_000  # probe ids; identical across replays for the same schedule
CLEANUP_ID_BASE = 1_500_000_000  # ids of cleanup market orders (queue-aware run only)


@dataclass(frozen=True)
class ProbeConfig:
    start: float = 1800.0
    end: float = 7140.0  # last decision time; end + max_wait must be <= horizon
    interval: float = 15.0
    size: int = 100
    max_wait: float = 60.0


@dataclass
class ProbeRecord:
    probe_id: int
    side: Side
    t: float
    posted: int | None  # None if that side of the book was empty (probe skipped)
    mid: float | None
    queue_ahead: int = 0  # shares resting at the posted price when the probe joined
    own_queue_ahead: int = 0  # part of queue_ahead that is this agent's own earlier probes
    deadline_opposite: int | None = None  # opposite best quote at the deadline
    deadline_mid: float | None = None  # mid at the deadline (for the markout)
    cleanup_id: int | None = None


@dataclass
class ProbeAgent:
    """Posts (``submit=True``) or merely records (``submit=False``) probes on a schedule."""

    config: ProbeConfig
    submit: bool
    records: dict[int, ProbeRecord] = field(default_factory=dict)
    _queue: list = field(default_factory=list)
    _next_id: int = PROBE_ID_BASE
    _next_cleanup_id: int = CLEANUP_ID_BASE

    def __post_init__(self) -> None:
        t = self.config.start
        k = 0
        while t <= self.config.end + 1e-9:
            heapq.heappush(self._queue, (t, 0, k, "decide", None))
            k += 1
            t = self.config.start + k * self.config.interval

    def next_time(self) -> float | None:
        return self._queue[0][0] if self._queue else None

    def act(self, t: float, engine: MatchingEngine) -> list[Event]:
        _, _, k, kind, pid = heapq.heappop(self._queue)
        book = engine.book
        out: list[Event] = []
        if kind == "decide":
            for side in (Side.BUY, Side.SELL):
                pid = self._next_id
                self._next_id += 1
                posted = book.best_price(side)
                rec = ProbeRecord(pid, side, t, posted, book.mid())
                self.records[pid] = rec
                if posted is None:
                    continue
                rec.queue_ahead = book.qty_at_price(side, posted)
                rec.own_queue_ahead = sum(
                    book.get(oid).qty for oid in book.queue(side, posted) if oid >= PROBE_ID_BASE
                )
                if self.submit:
                    out.append(LimitOrder(t, pid, side, posted, self.config.size))
                deadline = t + self.config.max_wait
                heapq.heappush(self._queue, (deadline, 1, k, "deadline", pid))
        else:
            rec = self.records[pid]
            rec.deadline_opposite = book.best_price(rec.side.opposite)
            rec.deadline_mid = book.mid()
            if self.submit and pid in book:
                remaining = book.get(pid).qty
                out.append(Cancel(t, pid))
                rec.cleanup_id = self._next_cleanup_id
                self._next_cleanup_id += 1
                out.append(MarketOrder(t, rec.cleanup_id, rec.side, remaining))
        return out


def _touch_fill_time(rec: ProbeRecord, trade_ts: np.ndarray, trade_px: np.ndarray,
                     max_wait: float) -> float | None:
    lo = np.searchsorted(trade_ts, rec.t, side="right")  # strictly after the decision
    hi = np.searchsorted(trade_ts, rec.t + max_wait, side="right")
    px = trade_px[lo:hi]
    hit = px <= rec.posted if rec.side is Side.BUY else px >= rec.posted
    idx = np.flatnonzero(hit)
    return None if idx.size == 0 else float(trade_ts[lo + idx[0]])


def run_comparison(
    events: list[Event], horizon: float, config: ProbeConfig | None = None
) -> tuple[pd.DataFrame, dict]:
    """Return one row per (probe, assumption) plus background-divergence stats."""
    config = config or ProbeConfig()
    base_agent = ProbeAgent(config, submit=False)
    base_run = replay(events, horizon, sample_interval=1.0, agents=[base_agent])
    live_agent = ProbeAgent(config, submit=True)
    live_run = replay(events, horizon, sample_interval=1.0, agents=[live_agent])
    base, live = base_run.engine, live_run.engine

    trade_ts = np.array([f.ts for f in base.fills])
    trade_px = np.array([f.price for f in base.fills])
    rows = []
    for pid, rec in base_agent.records.items():
        if rec.posted is None:
            rows.append({"probe_id": pid, "assumption": "naive", "skipped": True})
            rows.append({"probe_id": pid, "assumption": "touch", "skipped": True})
            continue
        common = {"probe_id": pid, "side": rec.side.value, "t": rec.t, "posted": rec.posted,
                  "mid": rec.mid, "mid_after": rec.deadline_mid, "skipped": False}
        rows.append({**common, "assumption": "naive", "passive_filled": True,
                     "exec_price": float(rec.posted), "time_to_fill": 0.0})
        t_fill = _touch_fill_time(rec, trade_ts, trade_px, config.max_wait)
        if t_fill is not None:
            rows.append({**common, "assumption": "touch", "passive_filled": True,
                         "exec_price": float(rec.posted), "time_to_fill": t_fill - rec.t})
        else:
            px = rec.deadline_opposite
            rows.append({**common, "assumption": "touch", "passive_filled": False,
                         "exec_price": np.nan if px is None else float(px),
                         "time_to_fill": np.nan})

    last_fill_ts: dict[int, float] = {}
    for f in live.fills:
        if f.resting_id >= PROBE_ID_BASE:
            last_fill_ts[f.resting_id] = f.ts

    for pid, rec in live_agent.records.items():
        if rec.posted is None:
            rows.append({"probe_id": pid, "assumption": "queue", "skipped": True})
            continue
        orec = live.orders[pid]
        passive_qty, notional = orec.filled, orec.notional
        unfilled = 0
        if rec.cleanup_id is not None:
            crec = live.orders[rec.cleanup_id]
            notional += crec.notional
            unfilled = crec.expired
        exec_qty = passive_qty
        if rec.cleanup_id is not None:
            exec_qty += live.orders[rec.cleanup_id].filled
        full = passive_qty == config.size
        rows.append({
            "probe_id": pid, "assumption": "queue", "side": rec.side.value, "t": rec.t,
            "posted": rec.posted, "mid": rec.mid, "mid_after": rec.deadline_mid,
            "skipped": False,
            "passive_filled": full, "passive_qty": passive_qty,
            "exec_price": notional / exec_qty if exec_qty else np.nan,
            "unfilled_after_cleanup": unfilled,
            "time_to_fill": (last_fill_ts[pid] - rec.t) if full else np.nan,
            "queue_ahead": rec.queue_ahead,
            "own_queue_ahead": rec.own_queue_ahead,
        })

    df = pd.DataFrame(rows)
    df["passive_filled"] = df["passive_filled"].astype("boolean")
    ok = ~df["skipped"]
    sign = df.loc[ok, "side"]
    df.loc[ok, "slippage_vs_posted"] = sign * (df.loc[ok, "exec_price"] - df.loc[ok, "posted"])
    df.loc[ok, "effective_spread"] = 2 * sign * (df.loc[ok, "exec_price"] - df.loc[ok, "mid"])
    # Positive markout = the price later moved in the probe's favour after it traded.
    df.loc[ok, "markout"] = sign * (df.loc[ok, "mid_after"] - df.loc[ok, "exec_price"])
    divergence = background_divergence(base, live)
    b, lv = base_run.snapshots, live_run.snapshots
    window = (b.t >= config.start) & (b.t <= config.end + config.max_wait)
    differ = ~(b.bid.eq(lv.bid) | (b.bid.isna() & lv.bid.isna())) | ~(
        b.ask.eq(lv.ask) | (b.ask.isna() & lv.ask.isna())
    )
    divergence["quote_samples_differing_frac"] = float(differ[window].mean())
    divergence["probes_posted_differently"] = sum(
        base_agent.records[pid].posted != live_agent.records[pid].posted
        for pid in base_agent.records
    )
    divergence["probes"] = len(base_agent.records)
    return df, divergence


def background_divergence(base: MatchingEngine, live: MatchingEngine) -> dict:
    """How much did inserting probes change what happened to background orders?"""

    def bg_fills(eng: MatchingEngine) -> set[tuple]:
        return {
            (f.ts, f.aggressor_id, f.resting_id, f.price, f.qty)
            for f in eng.fills
            if f.aggressor_id < PROBE_ID_BASE and f.resting_id < PROBE_ID_BASE
        }

    b, lv = bg_fills(base), bg_fills(live)
    return {
        # Background-vs-background fills in the no-probe replay that do not occur
        # identically (same time, counterparties, price and size) with probes present.
        # Any size change cascades through later partial fills, so this is a strict measure.
        "background_fills": len(b),
        "background_fills_not_reproduced": len(b - lv),
        "rejected_cancels_base": base.rejected_cancels,
        "rejected_cancels_live": live.rejected_cancels,
    }
