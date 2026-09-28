"""Partial fills, multi-level execution and exact volume accounting."""

from __future__ import annotations

from src.matching_engine import OrderStatus
from tests._util import BUY, SELL, lim, mkt, run


def test_large_aggressor_partially_fills_across_orders_and_levels():
    eng = run(
        [
            lim(0.0, 1, SELL, 100, 30),
            lim(0.0, 2, SELL, 100, 20),
            lim(0.0, 3, SELL, 101, 25),
        ]
    )
    before = eng.book.total_qty(SELL)
    res = eng.process(lim(1.0, 4, BUY, 101, 60))
    traded = sum(f.qty for f in res.fills)
    assert [(f.resting_id, f.qty) for f in res.fills] == [(1, 30), (2, 20), (3, 10)]
    assert traded == 60
    assert eng.book.total_qty(SELL) == before - traded
    assert eng.orders[4].filled == 60 and eng.orders[4].status is OrderStatus.FILLED
    assert eng.orders[3].filled == 10 and eng.book.get(3).qty == 15
    assert eng.orders[4].notional == 30 * 100 + 20 * 100 + 10 * 101
    eng.check_invariants()


def test_marketable_limit_remainder_rests_and_becomes_new_best():
    eng = run([lim(0.0, 1, SELL, 100, 10), lim(0.0, 2, SELL, 102, 10)])
    eng.process(lim(1.0, 3, BUY, 101, 25))
    assert eng.orders[3].filled == 10
    assert eng.book.get(3).qty == 15
    assert eng.orders[3].status is OrderStatus.PARTIALLY_FILLED
    assert eng.book.best_bid() == 101 and eng.book.best_ask() == 102
    eng.check_invariants()


def test_market_order_larger_than_book_expires_remainder():
    eng = run([lim(0.0, 1, BUY, 100, 10), lim(0.0, 2, BUY, 99, 10)])
    res = eng.process(mkt(1.0, 3, SELL, 50))
    assert sum(f.qty for f in res.fills) == 20
    rec = eng.orders[3]
    assert (rec.filled, rec.expired, rec.status) == (20, 30, OrderStatus.EXPIRED)
    assert eng.book.best_bid() is None
    eng.check_invariants()


def test_market_order_into_empty_book():
    eng = run([])
    res = eng.process(mkt(0.0, 1, BUY, 10))
    assert res.fills == ()
    assert eng.orders[1].expired == 10 and eng.orders[1].filled == 0
    assert len(eng.book) == 0
    eng.check_invariants()


def test_one_sided_book_limit_rests():
    eng = run([lim(0.0, 1, BUY, 100, 10)])
    res = eng.process(lim(1.0, 2, BUY, 101, 10))
    assert res.fills == () and eng.book.best_bid() == 101 and eng.book.best_ask() is None


def test_exact_fill_removes_level():
    eng = run([lim(0.0, 1, SELL, 100, 10), lim(0.0, 2, SELL, 101, 10)])
    eng.process(mkt(1.0, 3, BUY, 10))
    assert eng.book.levels(SELL) == [(101, 10)]
    assert eng.orders[1].status is OrderStatus.FILLED
    eng.check_invariants()


def test_repeated_market_orders_drain_queue_in_order():
    eng = run([lim(0.0, i, BUY, 100, 3) for i in range(1, 6)])
    order = []
    for k in range(8):
        order += [f.resting_id for f in eng.process(mkt(1.0 + k, 100 + k, SELL, 2)).fills]
        eng.check_invariants()
    # 16 shares of market sells in 2-lots against five 3-lots (15 shares):
    # [1] [1,2] [2] [3] [3,4] [4] [5] [5] and the last share expires.
    assert order == [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]
    assert eng.orders[107].expired == 1
    assert eng.book.total_qty(BUY) == 0


def test_extreme_quantities():
    big = 10**12
    eng = run([lim(0.0, 1, SELL, 100, big), lim(0.0, 2, SELL, 100, 1)])
    eng.process(mkt(1.0, 3, BUY, big))
    assert eng.book.queue(SELL, 100) == [2]
    eng.check_invariants()
