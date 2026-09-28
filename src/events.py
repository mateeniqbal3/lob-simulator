"""Typed order-flow events consumed by the matching engine.

Conventions used throughout the project:

* Prices are integer ticks, never floats, so price-level keys and price
  comparisons are exact.
* Quantities are positive integers (shares).
* ``ts`` is simulated time in seconds. The engine requires events to arrive
  in non-decreasing ``ts`` order (see ``MatchingEngine.process``).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Side(Enum):
    BUY = 1
    SELL = -1

    @property
    def opposite(self) -> Side:
        return Side.SELL if self is Side.BUY else Side.BUY


@dataclass(frozen=True, slots=True)
class LimitOrder:
    """Buy/sell up to ``qty`` at ``price`` or better; any unfilled remainder rests."""

    ts: float
    order_id: int
    side: Side
    price: int
    qty: int


@dataclass(frozen=True, slots=True)
class MarketOrder:
    """Buy/sell ``qty`` immediately at the best available prices.

    Any quantity that cannot be filled because the opposite side of the book
    is exhausted is discarded (immediate-or-cancel semantics); it never rests.
    """

    ts: float
    order_id: int
    side: Side
    qty: int


@dataclass(frozen=True, slots=True)
class Cancel:
    """Cancel a resting order.

    ``qty=None`` cancels the whole remaining quantity. A positive ``qty``
    smaller than the remaining quantity reduces the order in place, which
    keeps its queue position (standard exchange behaviour for size
    reductions).
    """

    ts: float
    order_id: int
    qty: int | None = None


Event = LimitOrder | MarketOrder | Cancel
