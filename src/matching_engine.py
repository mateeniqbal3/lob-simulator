"""Price-time priority matching engine.

Processes limit orders, market orders and cancellations against an
``OrderBook`` and records every fill.

Matching rules (continuous double auction, exchange-style):

* **Price priority**: an incoming order always trades against the best
  opposite price first (highest bid / lowest ask), walking to worse levels
  only once better ones are exhausted.
* **Time priority**: within a price level, resting orders trade in arrival
  order. A partial fill reduces the resting order in place, so its remainder
  keeps its original position.
* **Trade price** is the resting (passive) order's price.
* A limit order's unfilled remainder rests at its limit price; a market
  order's unfilled remainder is discarded (``EXPIRED``).

Look-ahead protection is structural: the engine only ever sees one event at
a time and refuses any event whose timestamp is earlier than the last one it
processed (``OutOfOrderEventError``). Nothing in the engine can inspect a
future event.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.events import Cancel, Event, LimitOrder, MarketOrder, Side
from src.order_book import BookInvariantError, OrderBook, RestingOrder


class OutOfOrderEventError(ValueError):
    """An event arrived with a timestamp earlier than one already processed."""


class OrderStatus(Enum):
    RESTING = "resting"  # on the book, nothing filled yet
    PARTIALLY_FILLED = "partially_filled"  # on the book, some quantity filled
    FILLED = "filled"  # fully executed
    CANCELLED = "cancelled"  # removed by a cancel (possibly after partial fills)
    EXPIRED = "expired"  # market order remainder discarded for lack of liquidity


@dataclass(slots=True)
class OrderRecord:
    """Lifecycle accounting for one submitted order.

    Invariant: ``qty == filled + cancelled + expired + resting`` where
    ``resting`` is the quantity currently on the book.
    """

    order_id: int
    side: Side
    kind: str  # "limit" or "market"
    price: int | None
    qty: int
    ts: float
    filled: int = 0
    cancelled: int = 0
    expired: int = 0
    status: OrderStatus = OrderStatus.RESTING
    notional: int = 0  # sum of fill price * fill qty, in ticks * shares

    @property
    def avg_fill_price(self) -> float | None:
        return self.notional / self.filled if self.filled else None


@dataclass(frozen=True, slots=True)
class Fill:
    ts: float
    fill_id: int
    price: int
    qty: int
    aggressor_id: int
    resting_id: int
    aggressor_side: Side


@dataclass(frozen=True, slots=True)
class EventResult:
    accepted: bool
    fills: tuple[Fill, ...] = ()
    reason: str | None = None


class MatchingEngine:
    def __init__(self) -> None:
        self.book = OrderBook()
        self.orders: dict[int, OrderRecord] = {}
        self.fills: list[Fill] = []
        self.last_ts = float("-inf")
        self.rejected_cancels = 0
        self._seq = 0

    # ------------------------------------------------------------------ public API

    def process(self, event: Event) -> EventResult:
        if event.ts < self.last_ts:
            raise OutOfOrderEventError(
                f"event at t={event.ts} arrived after t={self.last_ts} was processed"
            )
        if isinstance(event, LimitOrder):
            result = self._on_limit(event)
        elif isinstance(event, MarketOrder):
            result = self._on_market(event)
        elif isinstance(event, Cancel):
            result = self._on_cancel(event)
        else:
            raise TypeError(f"unknown event type {type(event).__name__}")
        self.last_ts = event.ts
        return result

    def resting_qty(self, order_id: int) -> int:
        order = self.book.get(order_id)
        return 0 if order is None else order.qty

    def check_invariants(self) -> None:
        """Verify book structure plus per-order and aggregate volume accounting."""
        self.book.check_invariants()
        for rec in self.orders.values():
            resting = self.resting_qty(rec.order_id)
            if rec.filled + rec.cancelled + rec.expired + resting != rec.qty:
                raise BookInvariantError(
                    f"order {rec.order_id}: filled {rec.filled} + cancelled {rec.cancelled} "
                    f"+ expired {rec.expired} + resting {resting} != qty {rec.qty}"
                )
            if min(rec.filled, rec.cancelled, rec.expired) < 0:
                raise BookInvariantError(f"order {rec.order_id} has negative accounting")
            on_book = rec.order_id in self.book
            if on_book != (rec.status in (OrderStatus.RESTING, OrderStatus.PARTIALLY_FILLED)):
                raise BookInvariantError(
                    f"order {rec.order_id} status {rec.status} but on_book={on_book}"
                )
        # Every unit traded is counted exactly once on each side of the trade.
        traded = sum(f.qty for f in self.fills)
        filled_total = sum(rec.filled for rec in self.orders.values())
        if filled_total != 2 * traded:
            raise BookInvariantError(
                f"sum of per-order fills {filled_total} != 2 x traded volume {traded}"
            )

    # ------------------------------------------------------------------ handlers

    def _register(self, rec: OrderRecord) -> None:
        if rec.qty <= 0 or not isinstance(rec.qty, int):
            raise ValueError(f"order {rec.order_id}: quantity must be a positive int")
        if rec.order_id in self.orders:
            raise ValueError(f"duplicate order id {rec.order_id}")
        self.orders[rec.order_id] = rec

    def _on_limit(self, ev: LimitOrder) -> EventResult:
        if not isinstance(ev.price, int):
            raise ValueError(f"order {ev.order_id}: price must be integer ticks")
        rec = OrderRecord(ev.order_id, ev.side, "limit", ev.price, ev.qty, ev.ts)
        self._register(rec)
        fills = self._match(rec, ev.ts, limit_price=ev.price)
        remaining = rec.qty - rec.filled
        if remaining > 0:
            self._seq += 1
            self.book.add(RestingOrder(ev.order_id, ev.side, ev.price, remaining, ev.ts, self._seq))
            rec.status = OrderStatus.PARTIALLY_FILLED if rec.filled else OrderStatus.RESTING
        else:
            rec.status = OrderStatus.FILLED
        return EventResult(True, tuple(fills))

    def _on_market(self, ev: MarketOrder) -> EventResult:
        rec = OrderRecord(ev.order_id, ev.side, "market", None, ev.qty, ev.ts)
        self._register(rec)
        fills = self._match(rec, ev.ts, limit_price=None)
        remaining = rec.qty - rec.filled
        if remaining > 0:
            rec.expired = remaining
            rec.status = OrderStatus.EXPIRED
        else:
            rec.status = OrderStatus.FILLED
        return EventResult(True, tuple(fills))

    def _on_cancel(self, ev: Cancel) -> EventResult:
        rec = self.orders.get(ev.order_id)
        if rec is None:
            self.rejected_cancels += 1
            return EventResult(False, reason="unknown order")
        resting = self.book.get(ev.order_id)
        if resting is None:
            self.rejected_cancels += 1
            return EventResult(False, reason=f"order not resting ({rec.status.value})")
        if ev.qty is None or ev.qty == resting.qty:
            qty = resting.qty
            self.book.remove(ev.order_id)
            rec.cancelled += qty
            rec.status = OrderStatus.CANCELLED
            return EventResult(True)
        if not isinstance(ev.qty, int) or ev.qty <= 0:
            raise ValueError(f"cancel of order {ev.order_id}: qty must be a positive int")
        if ev.qty > resting.qty:
            self.rejected_cancels += 1
            return EventResult(False, reason="cancel qty exceeds remaining qty")
        self.book.reduce(ev.order_id, ev.qty)  # keeps queue position
        rec.cancelled += ev.qty
        return EventResult(True)

    def _match(self, taker: OrderRecord, ts: float, limit_price: int | None) -> list[Fill]:
        fills: list[Fill] = []
        opp = taker.side.opposite
        remaining = taker.qty
        while remaining > 0:
            maker = self.book.peek_best(opp)
            if maker is None:
                break
            if limit_price is not None:
                if taker.side is Side.BUY and maker.price > limit_price:
                    break
                if taker.side is Side.SELL and maker.price < limit_price:
                    break
            qty = min(remaining, maker.qty)
            price = maker.price
            maker_id = maker.order_id
            self.book.reduce(maker_id, qty)  # removes the maker if fully filled

            maker_rec = self.orders[maker_id]
            maker_rec.filled += qty
            maker_rec.notional += qty * price
            maker_rec.status = (
                OrderStatus.FILLED if maker_id not in self.book else OrderStatus.PARTIALLY_FILLED
            )
            taker.filled += qty
            taker.notional += qty * price
            remaining -= qty

            fill = Fill(ts, len(self.fills), price, qty, taker.order_id, maker_id, taker.side)
            self.fills.append(fill)
            fills.append(fill)
        return fills
