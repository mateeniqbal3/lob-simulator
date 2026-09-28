"""The five required matching-engine correctness tests (PROJECT.md section 11).

Each test builds a small book by hand so the expected outcome can be read off
directly. Their ability to catch the bug each one targets is checked by
``scripts/mutation_check.py`` (see docs/engine_correctness.md).
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from src.matching_engine import MatchingEngine, OrderStatus, OutOfOrderEventError
from tests._util import BUY, SELL, book_state, cxl, fill_tuples, lim, mkt, random_events, run


def test_price_priority():
    """A better-priced order fills before a worse-priced one, regardless of arrival order."""
    eng = run(
        [
            lim(0.0, 1, SELL, 101, 10),  # worse price, arrived first
            lim(0.0, 2, SELL, 100, 10),  # better price, same timestamp, arrived second
            lim(0.0, 3, BUY, 98, 10),  # worse bid, arrived first
            lim(0.0, 4, BUY, 99, 10),  # better bid
        ]
    )
    res = eng.process(mkt(1.0, 5, BUY, 10))
    assert [(f.resting_id, f.price, f.qty) for f in res.fills] == [(2, 100, 10)]
    assert eng.orders[1].filled == 0

    res = eng.process(mkt(2.0, 6, SELL, 10))
    assert [(f.resting_id, f.price, f.qty) for f in res.fills] == [(4, 99, 10)]
    assert eng.orders[3].filled == 0

    # A marketable limit order walks levels best-first and stops at its limit.
    eng = run(
        [
            lim(0.0, 1, SELL, 102, 5),
            lim(0.0, 2, SELL, 101, 5),
            lim(0.0, 3, SELL, 100, 5),
            lim(0.0, 4, SELL, 103, 5),
        ]
    )
    res = eng.process(lim(1.0, 5, BUY, 102, 20))
    assert [(f.resting_id, f.price) for f in res.fills] == [(3, 100), (2, 101), (1, 102)]
    assert eng.book.best_bid() == 102 and eng.book.best_ask() == 103
    assert eng.book.get(5).qty == 5  # remainder rests at its limit
    eng.check_invariants()


def test_time_priority_within_level():
    """Earlier orders at the same price fill before later ones at that price."""
    eng = run(
        [
            lim(0.0, 1, BUY, 100, 10),
            lim(1.0, 2, BUY, 100, 10),
            lim(1.0, 3, BUY, 100, 10),  # same timestamp as 2: arrival sequence decides
            lim(2.0, 4, BUY, 100, 10),
        ]
    )
    assert eng.book.queue(BUY, 100) == [1, 2, 3, 4]
    res = eng.process(mkt(3.0, 5, SELL, 35))
    assert [(f.resting_id, f.qty) for f in res.fills] == [(1, 10), (2, 10), (3, 10), (4, 5)]
    assert eng.book.queue(BUY, 100) == [4]

    # A later order at the same price joins the back even after the front has traded.
    eng.process(lim(4.0, 6, BUY, 100, 10))
    assert eng.book.queue(BUY, 100) == [4, 6]
    res = eng.process(mkt(5.0, 7, SELL, 6))
    assert [(f.resting_id, f.qty) for f in res.fills] == [(4, 5), (6, 1)]
    eng.check_invariants()


def test_partial_fill_preserves_queue_position():
    """A partially filled order's remaining quantity keeps its original time priority."""
    eng = run(
        [
            lim(0.0, 1, SELL, 100, 100),
            lim(1.0, 2, SELL, 100, 50),
            lim(2.0, 3, SELL, 100, 50),
        ]
    )
    res = eng.process(mkt(3.0, 4, BUY, 40))
    assert [(f.resting_id, f.qty) for f in res.fills] == [(1, 40)]
    assert eng.book.get(1).qty == 60
    assert eng.orders[1].status is OrderStatus.PARTIALLY_FILLED
    assert eng.book.queue(SELL, 100) == [1, 2, 3]  # still at the front
    assert eng.book.queue_position(1).rank == 0
    assert eng.book.queue_position(2).qty_ahead == 60

    # New arrivals go behind the partially filled order, not in front of it.
    eng.process(lim(4.0, 5, SELL, 100, 10))
    assert eng.book.queue(SELL, 100) == [1, 2, 3, 5]

    # The next aggressor finishes order 1 first, then moves on to order 2.
    res = eng.process(mkt(5.0, 6, BUY, 70))
    assert [(f.resting_id, f.qty) for f in res.fills] == [(1, 60), (2, 10)]
    assert eng.orders[1].status is OrderStatus.FILLED
    assert eng.book.queue(SELL, 100) == [2, 3, 5]
    assert eng.book.get(2).qty == 40

    # A size reduction (partial cancel) also keeps priority.
    eng.process(cxl(6.0, 2, 30))
    assert eng.book.queue(SELL, 100) == [2, 3, 5]
    assert eng.book.get(2).qty == 10
    eng.check_invariants()


def test_cancellation_correctness():
    """Cancelling removes exactly that order without disturbing others' queue positions."""
    eng = run(
        [
            lim(0.0, 1, BUY, 100, 10),
            lim(1.0, 2, BUY, 100, 20),
            lim(2.0, 3, BUY, 100, 30),
            lim(3.0, 4, BUY, 100, 40),
            lim(3.0, 9, BUY, 99, 5),
        ]
    )
    res = eng.process(cxl(4.0, 2))
    assert res.accepted
    assert eng.book.queue(BUY, 100) == [1, 3, 4]
    assert eng.book.qty_at_price(BUY, 100) == 80
    assert eng.orders[2].status is OrderStatus.CANCELLED and eng.orders[2].cancelled == 20
    pos3, pos4 = eng.book.queue_position(3), eng.book.queue_position(4)
    assert (pos3.rank, pos3.qty_ahead) == (1, 10)
    assert (pos4.rank, pos4.qty_ahead) == (2, 40)
    assert eng.book.queue(BUY, 99) == [9]  # other levels untouched

    # The cancelled order never trades; the survivors trade in their original order.
    res = eng.process(mkt(5.0, 5, SELL, 1000))
    assert [f.resting_id for f in res.fills] == [1, 3, 4, 9]
    assert 2 not in [f.resting_id for f in eng.fills]

    # Repeated, post-fill and unknown cancels are rejected without side effects.
    before = book_state(eng)
    for oid in (2, 1, 12345):
        assert not eng.process(cxl(6.0, oid)).accepted
    assert book_state(eng) == before
    assert eng.rejected_cancels == 3
    eng.check_invariants()


def test_no_lookahead():
    """No simulated event or metric uses information from a future timestamp.

    Structural checks at the engine level:
    1. The engine refuses events that go back in time, leaving state untouched.
    2. The state after the first k events is identical whether or not later
       events are ever processed (fills already reported are never revised).
    3. Whatever follows event k, the output up to k is unchanged.
    The simulation-level counterpart (sampled metrics as of T) is in
    tests/test_simulation.py.
    """
    eng = run([lim(5.0, 1, BUY, 100, 10)])
    before = book_state(eng)
    with pytest.raises(OutOfOrderEventError):
        eng.process(lim(4.9, 2, SELL, 99, 10))
    assert book_state(eng) == before and 2 not in eng.orders

    events = random_events(seed=7, n=300)
    full = MatchingEngine()
    prefix_states, prefix_fills = [], []
    for ev in events:
        full.process(ev)
        prefix_states.append(book_state(full))
        prefix_fills.append(list(fill_tuples(full)))
    final_fills = fill_tuples(full)
    for k in (1, 10, 75, 150, 299):
        partial = run(events[: k + 1], check=False)
        assert book_state(partial) == prefix_states[k]
        assert fill_tuples(partial) == prefix_fills[k]
        assert final_fills[: len(prefix_fills[k])] == prefix_fills[k]

    # Replace everything after k with a different future: the past is unchanged.
    k = 150
    t_k = events[k].ts
    alt_future = [
        replace(ev, ts=t_k + ev.ts, order_id=ev.order_id + 100_000)
        for ev in random_events(seed=99, n=300)
    ]
    alt = run(events[: k + 1] + alt_future)
    assert fill_tuples(alt)[: len(prefix_fills[k])] == prefix_fills[k]
    assert fill_tuples(alt) != final_fills  # the future really was different
