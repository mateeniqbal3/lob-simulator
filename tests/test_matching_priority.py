"""Adversarial price-time priority cases beyond the five core tests."""

from __future__ import annotations

from tests._util import BUY, SELL, lim, mkt, run


def test_later_better_price_jumps_earlier_worse_price():
    eng = run([lim(0.0, 1, BUY, 99, 10), lim(5.0, 2, BUY, 100, 10)])
    res = eng.process(mkt(6.0, 3, SELL, 10))
    assert [f.resting_id for f in res.fills] == [2]


def test_time_priority_holds_at_every_level_while_walking_the_book():
    eng = run(
        [
            lim(0.0, 1, SELL, 101, 5),
            lim(1.0, 2, SELL, 100, 5),
            lim(2.0, 3, SELL, 101, 5),
            lim(3.0, 4, SELL, 100, 5),
            lim(4.0, 5, SELL, 102, 5),
        ]
    )
    res = eng.process(mkt(5.0, 6, BUY, 22))
    assert [(f.resting_id, f.price, f.qty) for f in res.fills] == [
        (2, 100, 5),
        (4, 100, 5),
        (1, 101, 5),
        (3, 101, 5),
        (5, 102, 2),
    ]
    assert eng.book.queue(SELL, 102) == [5] and eng.book.get(5).qty == 3


def test_same_side_order_at_existing_price_joins_back_of_queue():
    eng = run([lim(0.0, 1, SELL, 100, 5), lim(0.0, 2, SELL, 100, 5)])
    eng.process(lim(0.0, 3, SELL, 100, 5))
    assert eng.book.queue(SELL, 100) == [1, 2, 3]


def test_trade_price_is_resting_price_not_aggressor_limit():
    eng = run([lim(0.0, 1, SELL, 100, 5)])
    res = eng.process(lim(1.0, 2, BUY, 105, 5))
    assert [(f.price, f.qty) for f in res.fills] == [(100, 5)]
    assert eng.orders[2].avg_fill_price == 100


def test_symmetric_for_sell_aggressor():
    eng = run([lim(0.0, 1, BUY, 100, 5), lim(1.0, 2, BUY, 101, 5), lim(2.0, 3, BUY, 101, 5)])
    res = eng.process(lim(3.0, 4, SELL, 100, 12))
    assert [(f.resting_id, f.price, f.qty) for f in res.fills] == [
        (2, 101, 5),
        (3, 101, 5),
        (1, 100, 2),
    ]
    assert eng.book.best_bid() == 100 and eng.book.best_ask() is None


def test_non_marketable_limit_never_trades():
    eng = run([lim(0.0, 1, SELL, 101, 5)])
    res = eng.process(lim(1.0, 2, BUY, 100, 5))
    assert res.fills == () and eng.book.best_bid() == 100 and eng.book.best_ask() == 101
