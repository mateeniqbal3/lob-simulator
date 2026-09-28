"""Structural tests for the order book data structure on its own (no matching)."""

from __future__ import annotations

import pytest

from src.events import Side
from src.order_book import BookInvariantError, OrderBook, RestingOrder

BUY, SELL = Side.BUY, Side.SELL
_seq = iter(range(1, 10**9))


def order(oid, side, price, qty, ts=0.0):
    return RestingOrder(oid, side, price, qty, ts, next(_seq))


@pytest.fixture
def book():
    b = OrderBook()
    b.add(order(1, BUY, 99, 10))
    b.add(order(2, BUY, 100, 20))
    b.add(order(3, BUY, 100, 30))
    b.add(order(4, SELL, 102, 5))
    b.add(order(5, SELL, 104, 7))
    return b


def test_best_prices_spread_mid(book):
    assert (book.best_bid(), book.best_ask(), book.spread(), book.mid()) == (100, 102, 2, 101.0)


def test_empty_book_queries():
    b = OrderBook()
    assert b.best_bid() is None and b.best_ask() is None
    assert b.spread() is None and b.mid() is None and b.peek_best(BUY) is None
    assert b.levels(SELL) == [] and b.depth_at_level(BUY, 1) == 0
    b.check_invariants()


def test_levels_and_depth(book):
    assert book.levels(BUY) == [(100, 50), (99, 10)]
    assert book.levels(SELL, n=1) == [(102, 5)]
    assert [book.depth_at_level(BUY, k) for k in (1, 2, 3)] == [50, 10, 0]
    assert [book.depth_at_level(SELL, k) for k in (1, 2, 3)] == [5, 7, 0]
    assert book.qty_at_price(BUY, 100) == 50 and book.qty_at_price(BUY, 98) == 0
    assert book.total_qty(BUY) == 60 and len(book) == 5
    with pytest.raises(ValueError):
        book.depth_at_level(BUY, 0)


def test_queue_and_position(book):
    assert book.queue(BUY, 100) == [2, 3]
    assert book.peek_best(BUY).order_id == 2
    pos = book.queue_position(3)
    assert (pos.rank, pos.qty_ahead, pos.level_qty) == (1, 20, 50)


def test_remove_updates_level_and_drops_empty_level(book):
    book.remove(2)
    assert book.queue(BUY, 100) == [3] and book.qty_at_price(BUY, 100) == 30
    book.remove(3)
    assert book.best_bid() == 99
    assert 3 not in book
    with pytest.raises(KeyError):
        book.remove(3)
    book.check_invariants()


def test_reduce_keeps_position_and_removes_at_zero(book):
    book.reduce(2, 5)
    assert book.queue(BUY, 100) == [2, 3] and book.get(2).qty == 15
    assert book.qty_at_price(BUY, 100) == 45
    book.reduce(2, 15)
    assert book.queue(BUY, 100) == [3]
    for bad in (0, -1, 31):
        with pytest.raises(ValueError):
            book.reduce(3, bad)
    book.check_invariants()


def test_add_rejects_crossing_duplicate_and_nonpositive(book):
    with pytest.raises(ValueError):
        book.add(order(10, BUY, 102, 1))  # would cross the ask
    with pytest.raises(ValueError):
        book.add(order(11, SELL, 100, 1))  # would cross the bid
    with pytest.raises(ValueError):
        book.add(order(1, BUY, 98, 1))  # duplicate id
    with pytest.raises(ValueError):
        book.add(order(12, BUY, 98, 0))
    book.check_invariants()


def test_invariant_checker_detects_corruption(book):
    book.get(2).qty += 1  # level total no longer matches
    with pytest.raises(BookInvariantError):
        book.check_invariants()


def test_invariant_checker_detects_priority_violation():
    b = OrderBook()
    b.add(RestingOrder(1, BUY, 100, 5, 0.0, seq=5))
    b.add(RestingOrder(2, BUY, 100, 5, 0.0, seq=3))  # later in queue but earlier seq
    with pytest.raises(BookInvariantError):
        b.check_invariants()
