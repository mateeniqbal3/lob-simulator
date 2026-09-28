"""A deliberately naive, obviously-correct reference matcher for differential testing.

It stores resting orders in a flat list and re-sorts the opposite side by
(price priority, arrival sequence) before every single match. It is slow but
shares no data structures or code with ``src/``, so agreement between the two
on random streams is strong evidence that the real engine's priority logic is
right.
"""

from __future__ import annotations

from src.events import Cancel, Event, LimitOrder, MarketOrder, Side


class ReferenceEngine:
    def __init__(self) -> None:
        self.resting: list[dict] = []  # {"id", "side", "price", "qty", "seq"}
        self.fills: list[tuple[int, int, int, int]] = []  # (aggressor, resting, price, qty)
        self.known: set[int] = set()
        self.seq = 0

    def _priority_sorted(self, side: Side) -> list[dict]:
        orders = [o for o in self.resting if o["side"] is side]
        if side is Side.BUY:
            return sorted(orders, key=lambda o: (-o["price"], o["seq"]))
        return sorted(orders, key=lambda o: (o["price"], o["seq"]))

    def process(self, ev: Event) -> None:
        if isinstance(ev, Cancel):
            for o in self.resting:
                if o["id"] == ev.order_id:
                    if ev.qty is None or ev.qty == o["qty"]:
                        self.resting.remove(o)
                    elif ev.qty < o["qty"]:
                        o["qty"] -= ev.qty
                    return
            return
        self.known.add(ev.order_id)
        limit = ev.price if isinstance(ev, LimitOrder) else None
        remaining = ev.qty
        while remaining > 0:
            book = self._priority_sorted(ev.side.opposite)
            if not book:
                break
            best = book[0]
            if limit is not None and (
                (ev.side is Side.BUY and best["price"] > limit)
                or (ev.side is Side.SELL and best["price"] < limit)
            ):
                break
            q = min(remaining, best["qty"])
            self.fills.append((ev.order_id, best["id"], best["price"], q))
            best["qty"] -= q
            remaining -= q
            if best["qty"] == 0:
                self.resting.remove(best)
        if isinstance(ev, LimitOrder) and remaining > 0:
            self.seq += 1
            self.resting.append(
                {"id": ev.order_id, "side": ev.side, "price": ev.price, "qty": remaining,
                 "seq": self.seq}
            )
        assert not isinstance(ev, MarketOrder) or remaining >= 0

    def book_state(self) -> dict:
        state = {}
        for side in (Side.BUY, Side.SELL):
            levels: dict[int, list[tuple[int, int]]] = {}
            for o in self._priority_sorted(side):
                levels.setdefault(o["price"], []).append((o["id"], o["qty"]))
            state[side.name] = list(levels.items())
        return state
