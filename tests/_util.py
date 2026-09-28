"""Shared helpers for the test suite."""

from __future__ import annotations

import random

from src.events import Cancel, Event, LimitOrder, MarketOrder, Side
from src.matching_engine import MatchingEngine

BUY, SELL = Side.BUY, Side.SELL


def lim(ts: float, oid: int, side: Side, price: int, qty: int) -> LimitOrder:
    return LimitOrder(ts=ts, order_id=oid, side=side, price=price, qty=qty)


def mkt(ts: float, oid: int, side: Side, qty: int) -> MarketOrder:
    return MarketOrder(ts=ts, order_id=oid, side=side, qty=qty)


def cxl(ts: float, oid: int, qty: int | None = None) -> Cancel:
    return Cancel(ts=ts, order_id=oid, qty=qty)


def run(events: list[Event], check: bool = True) -> MatchingEngine:
    eng = MatchingEngine()
    for ev in events:
        eng.process(ev)
        if check:
            eng.check_invariants()
    return eng


def book_state(eng: MatchingEngine) -> dict:
    """A plain, comparable description of the full book: every queue, in order."""
    state = {}
    for side in (BUY, SELL):
        state[side.name] = [
            (price, [(oid, eng.book.get(oid).qty) for oid in eng.book.queue(side, price)])
            for price, _ in eng.book.levels(side)
        ]
    return state


def fill_tuples(eng: MatchingEngine) -> list[tuple]:
    return [(f.aggressor_id, f.resting_id, f.price, f.qty) for f in eng.fills]


def random_events(seed: int, n: int = 400, price_lo: int = 95, price_hi: int = 105) -> list[Event]:
    """Adversarial random stream: narrow price band (many marketable limits),
    duplicate timestamps, market orders that can exceed the book, partial and
    full cancels of live, filled and unknown orders."""
    rng = random.Random(seed)
    events: list[Event] = []
    ts = 0.0
    next_id = 1
    ids: list[int] = []
    for _ in range(n):
        if rng.random() < 0.7:
            ts += rng.choice([0.0, 0.0, 0.5, 1.0])  # frequent exact ties
        r = rng.random()
        side = rng.choice([BUY, SELL])
        if r < 0.55:
            price = rng.randint(price_lo, price_hi)
            events.append(lim(ts, next_id, side, price, rng.randint(1, 10)))
            ids.append(next_id)
            next_id += 1
        elif r < 0.70:
            events.append(mkt(ts, next_id, side, rng.randint(1, 40)))
            ids.append(next_id)
            next_id += 1
        elif r < 0.85 and ids:
            events.append(cxl(ts, rng.choice(ids)))
        elif r < 0.95 and ids:
            events.append(cxl(ts, rng.choice(ids), rng.randint(1, 5)))
        else:
            events.append(cxl(ts, 10_000 + rng.randint(0, 50)))  # unknown id
    return events
