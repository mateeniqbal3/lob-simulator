"""Order lifecycle, cancellation accounting and the never-crossed invariant."""

from __future__ import annotations

import pytest

from src.matching_engine import MatchingEngine, OrderStatus
from tests._util import BUY, SELL, cxl, lim, mkt, random_events, run


def test_cancel_removes_exactly_remaining_qty():
    eng = run([lim(0.0, 1, SELL, 100, 50), lim(0.0, 2, SELL, 100, 20)])
    eng.process(mkt(1.0, 3, BUY, 30))
    eng.process(cxl(2.0, 1))
    rec = eng.orders[1]
    assert (rec.filled, rec.cancelled, rec.status) == (30, 20, OrderStatus.CANCELLED)
    assert eng.book.levels(SELL) == [(100, 20)]
    eng.check_invariants()


def test_cancel_immediately_before_execution():
    eng = run([lim(0.0, 1, BUY, 100, 10), lim(0.0, 2, BUY, 100, 10)])
    eng.process(cxl(1.0, 1))
    res = eng.process(mkt(1.0, 3, SELL, 10))  # same timestamp, processed after the cancel
    assert [f.resting_id for f in res.fills] == [2]


def test_cancel_behind_active_queue_does_not_move_front():
    eng = run([lim(0.0, i, SELL, 100, 10) for i in range(1, 6)])
    eng.process(mkt(1.0, 10, BUY, 5))  # order 1 partially filled, at the front
    eng.process(cxl(2.0, 4))
    assert eng.book.queue(SELL, 100) == [1, 2, 3, 5]
    assert eng.book.queue_position(1).rank == 0 and eng.book.get(1).qty == 5
    assert eng.book.queue_position(5).qty_ahead == 5 + 10 + 10


def test_cancel_of_whole_level_removes_level():
    eng = run([lim(0.0, 1, BUY, 100, 10), lim(0.0, 2, BUY, 99, 10)])
    eng.process(cxl(1.0, 1))
    assert eng.book.best_bid() == 99
    eng.check_invariants()


def test_partial_cancel_rules():
    eng = run([lim(0.0, 1, BUY, 100, 10)])
    assert not eng.process(cxl(1.0, 1, 11)).accepted  # more than remaining
    assert eng.book.get(1).qty == 10
    assert eng.process(cxl(1.0, 1, 10)).accepted  # exactly remaining = full cancel
    assert eng.orders[1].status is OrderStatus.CANCELLED
    with pytest.raises(ValueError):
        run([lim(0.0, 2, BUY, 100, 10)]).process(cxl(1.0, 2, -1))


@pytest.mark.parametrize(
    "event",
    [
        lim(0.0, 1, BUY, 100, 0),
        lim(0.0, 1, BUY, 100, -5),
        mkt(0.0, 1, BUY, 0),
    ],
)
def test_invalid_quantities_fail_loudly(event):
    eng = MatchingEngine()
    with pytest.raises(ValueError):
        eng.process(event)
    assert not eng.orders and len(eng.book) == 0


def test_non_integer_price_rejected():
    with pytest.raises(ValueError):
        MatchingEngine().process(lim(0.0, 1, BUY, 100.5, 10))


def test_duplicate_order_id_rejected():
    eng = run([lim(0.0, 1, BUY, 100, 10)])
    with pytest.raises(ValueError):
        eng.process(lim(1.0, 1, SELL, 105, 10))
    assert eng.book.best_ask() is None


def test_filled_and_cancelled_orders_are_not_executable():
    eng = run([lim(0.0, 1, SELL, 100, 10), lim(0.0, 2, SELL, 100, 10), lim(0.0, 3, SELL, 101, 5)])
    eng.process(mkt(1.0, 4, BUY, 10))  # fills 1
    eng.process(cxl(2.0, 2))
    res = eng.process(mkt(3.0, 5, BUY, 100))
    assert [f.resting_id for f in res.fills] == [3]


@pytest.mark.parametrize("seed", range(40))
def test_book_never_left_crossed(seed):
    eng = MatchingEngine()
    for ev in random_events(seed, n=300):
        eng.process(ev)
        assert not eng.book.is_crossed()
        for o in eng.book.resting_orders():
            assert o.qty > 0
            assert eng.orders[o.order_id].status in (
                OrderStatus.RESTING,
                OrderStatus.PARTIALLY_FILLED,
            )
