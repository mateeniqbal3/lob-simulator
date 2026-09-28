"""Limit order book state: price levels, each holding a FIFO queue of resting orders.

This module owns book *state* only. It never decides who trades with whom;
that is ``matching_engine.py``'s job. The book does, however, refuse to enter
states that no correct matching engine could produce (a crossed book,
non-positive resting quantity, duplicate order ids) and raises instead.

Time priority within a level is the insertion order of an ``OrderedDict``:
new orders are appended at the back, and partial fills or size reductions
modify an order in place, so they never change its position.
"""

from __future__ import annotations

import bisect
from collections import OrderedDict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from src.events import Side


class BookInvariantError(AssertionError):
    """Raised when the book's internal state is inconsistent."""


@dataclass(slots=True)
class RestingOrder:
    order_id: int
    side: Side
    price: int
    qty: int  # remaining quantity
    ts: float
    seq: int  # arrival sequence number assigned by the engine


@dataclass(frozen=True, slots=True)
class QueuePosition:
    rank: int  # number of orders ahead at the same price (0 = front of queue)
    qty_ahead: int  # total quantity resting ahead at the same price
    level_qty: int  # total quantity resting at this price level, including this order


class PriceLevel:
    __slots__ = ("price", "orders", "total_qty")

    def __init__(self, price: int) -> None:
        self.price = price
        self.orders: OrderedDict[int, RestingOrder] = OrderedDict()
        self.total_qty = 0


class OrderBook:
    def __init__(self) -> None:
        self._levels: dict[Side, dict[int, PriceLevel]] = {Side.BUY: {}, Side.SELL: {}}
        # Ascending sorted prices per side. Best bid is the last bid price,
        # best ask the first ask price.
        self._prices: dict[Side, list[int]] = {Side.BUY: [], Side.SELL: []}
        self._index: dict[int, RestingOrder] = {}

    # ------------------------------------------------------------------ mutation

    def add(self, order: RestingOrder) -> None:
        """Append ``order`` to the back of its price level's queue."""
        if order.qty <= 0:
            raise ValueError(f"resting quantity must be positive, got {order.qty}")
        if order.order_id in self._index:
            raise ValueError(f"order id {order.order_id} is already resting")
        opp = self.best_price(order.side.opposite)
        if opp is not None and (
            (order.side is Side.BUY and order.price >= opp)
            or (order.side is Side.SELL and order.price <= opp)
        ):
            raise ValueError(
                f"adding {order.side.name} @ {order.price} would cross the book "
                f"(opposite best {opp}); marketable orders must be matched first"
            )
        levels = self._levels[order.side]
        level = levels.get(order.price)
        if level is None:
            level = PriceLevel(order.price)
            levels[order.price] = level
            bisect.insort(self._prices[order.side], order.price)
        level.orders[order.order_id] = order
        level.total_qty += order.qty
        self._index[order.order_id] = order

    def remove(self, order_id: int) -> RestingOrder:
        """Remove a resting order entirely. Other orders keep their relative order."""
        order = self._index.pop(order_id)  # KeyError if not resting
        level = self._levels[order.side][order.price]
        del level.orders[order_id]
        level.total_qty -= order.qty
        if not level.orders:
            self._drop_level(order.side, order.price)
        return order

    def reduce(self, order_id: int, qty: int) -> RestingOrder:
        """Reduce a resting order's quantity in place (partial fill or size reduction).

        The order keeps its queue position. If the remaining quantity reaches
        zero, the order is removed from the book.
        """
        order = self._index[order_id]
        if not 0 < qty <= order.qty:
            raise ValueError(f"cannot reduce order {order_id} (remaining {order.qty}) by {qty}")
        level = self._levels[order.side][order.price]
        order.qty -= qty
        level.total_qty -= qty
        if order.qty == 0:
            self.remove(order_id)
        return order

    def _drop_level(self, side: Side, price: int) -> None:
        del self._levels[side][price]
        prices = self._prices[side]
        i = bisect.bisect_left(prices, price)
        del prices[i]

    # ------------------------------------------------------------------ queries

    def __contains__(self, order_id: int) -> bool:
        return order_id in self._index

    def __len__(self) -> int:
        return len(self._index)

    def get(self, order_id: int) -> RestingOrder | None:
        return self._index.get(order_id)

    def order_ids(self) -> list[int]:
        return list(self._index)

    def best_price(self, side: Side) -> int | None:
        prices = self._prices[side]
        if not prices:
            return None
        return prices[-1] if side is Side.BUY else prices[0]

    def best_bid(self) -> int | None:
        return self.best_price(Side.BUY)

    def best_ask(self) -> int | None:
        return self.best_price(Side.SELL)

    def spread(self) -> int | None:
        bid, ask = self.best_bid(), self.best_ask()
        if bid is None or ask is None:
            return None
        return ask - bid

    def mid(self) -> float | None:
        bid, ask = self.best_bid(), self.best_ask()
        if bid is None or ask is None:
            return None
        return (bid + ask) / 2

    def peek_best(self, side: Side) -> RestingOrder | None:
        """The order at the front of the queue at the best price on ``side``."""
        price = self.best_price(side)
        if price is None:
            return None
        return next(iter(self._levels[side][price].orders.values()))

    def _prices_best_first(self, side: Side) -> Iterable[int]:
        prices = self._prices[side]
        return reversed(prices) if side is Side.BUY else prices

    def levels(self, side: Side, n: int | None = None) -> list[tuple[int, int]]:
        """``(price, total_qty)`` for the ``n`` best price levels, best first."""
        out: list[tuple[int, int]] = []
        for price in self._prices_best_first(side):
            if n is not None and len(out) >= n:
                break
            out.append((price, self._levels[side][price].total_qty))
        return out

    def depth_at_level(self, side: Side, k: int) -> int:
        """Total quantity at the k-th best occupied price level (1-indexed); 0 if none."""
        if k < 1:
            raise ValueError("levels are 1-indexed")
        prices = self._prices[side]
        if k > len(prices):
            return 0
        price = prices[-k] if side is Side.BUY else prices[k - 1]
        return self._levels[side][price].total_qty

    def qty_at_price(self, side: Side, price: int) -> int:
        level = self._levels[side].get(price)
        return 0 if level is None else level.total_qty

    def queue(self, side: Side, price: int) -> list[int]:
        """Order ids resting at ``price`` in priority order (front first)."""
        level = self._levels[side].get(price)
        return [] if level is None else list(level.orders)

    def queue_position(self, order_id: int) -> QueuePosition:
        order = self._index[order_id]
        level = self._levels[order.side][order.price]
        rank = 0
        ahead = 0
        for oid, o in level.orders.items():
            if oid == order_id:
                return QueuePosition(rank=rank, qty_ahead=ahead, level_qty=level.total_qty)
            rank += 1
            ahead += o.qty
        raise BookInvariantError(f"order {order_id} indexed but missing from its level")

    def total_qty(self, side: Side) -> int:
        return sum(level.total_qty for level in self._levels[side].values())

    def resting_orders(self) -> Iterator[RestingOrder]:
        return iter(self._index.values())

    def is_crossed(self) -> bool:
        bid, ask = self.best_bid(), self.best_ask()
        return bid is not None and ask is not None and bid >= ask

    # ------------------------------------------------------------------ invariants

    def check_invariants(self) -> None:
        """Recompute everything from scratch and raise ``BookInvariantError`` on mismatch."""
        seen: set[int] = set()
        for side in (Side.BUY, Side.SELL):
            levels = self._levels[side]
            prices = self._prices[side]
            if prices != sorted(levels):
                raise BookInvariantError(f"{side.name} price index out of sync with levels")
            if len(set(prices)) != len(prices):
                raise BookInvariantError(f"{side.name} duplicate price in index")
            for price, level in levels.items():
                if level.price != price:
                    raise BookInvariantError("level keyed under wrong price")
                if not level.orders:
                    raise BookInvariantError(f"empty level left at {side.name} {price}")
                total = 0
                last_seq = -1
                for oid, o in level.orders.items():
                    if oid != o.order_id:
                        raise BookInvariantError("order keyed under wrong id")
                    if o.qty <= 0:
                        raise BookInvariantError(f"order {oid} rests with qty {o.qty}")
                    if o.side is not side or o.price != price:
                        raise BookInvariantError(f"order {oid} filed under wrong side/price")
                    if o.seq <= last_seq:
                        raise BookInvariantError(f"time priority violated at {side.name} {price}")
                    if oid in seen:
                        raise BookInvariantError(f"order {oid} rests in more than one queue")
                    if self._index.get(oid) is not o:
                        raise BookInvariantError(f"order {oid} missing from index")
                    seen.add(oid)
                    last_seq = o.seq
                    total += o.qty
                if total != level.total_qty:
                    raise BookInvariantError(
                        f"level total {level.total_qty} != sum of orders {total} "
                        f"at {side.name} {price}"
                    )
        if seen != set(self._index):
            raise BookInvariantError("index contains orders that are in no queue")
        if self.is_crossed():
            bid, ask = self.best_bid(), self.best_ask()
            raise BookInvariantError(f"book crossed: bid {bid} >= ask {ask}")
