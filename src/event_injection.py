"""The controlled liquidity stress scenario (parameters pre-specified in DECISIONS.md ADR-002).

The stress event is a temporary, one-sided burst of aggressive order flow:
during ``[start, start + duration)`` the market-order arrival rate on
``side`` is multiplied by ``market_multiplier``. Nothing else about the model
changes: limit-order arrival, placement, sizes and cancellation all keep
their baseline parameters, so any change in liquidity around the event is
attributable to the burst and the book's own response to it.

This is a designed scenario applied to synthetic order flow, not a model of
any particular historical market event.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.events import Side
from src.order_flow import OrderFlowParams, Rates


@dataclass(frozen=True)
class StressScenario:
    start: float
    duration: float
    side: Side = Side.SELL
    market_multiplier: float = 5.0

    @property
    def end(self) -> float:
        return self.start + self.duration

    def active(self, t: float) -> bool:
        return self.start <= t < self.end

    def rates(self, t: float, base: OrderFlowParams) -> Rates:
        mb = ms = base.market_rate
        if self.active(t):
            if self.side is Side.BUY:
                mb *= self.market_multiplier
            else:
                ms *= self.market_multiplier
        return Rates(base.limit_rate, base.limit_rate, mb, ms)

    def breakpoints(self) -> list[float]:
        return [self.start, self.end]
