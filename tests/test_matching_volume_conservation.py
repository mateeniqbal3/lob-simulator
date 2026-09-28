"""Randomised volume-conservation and differential tests.

Instead of adding the ``hypothesis`` dependency, these tests drive the engine
with many seeded adversarial random streams (see ``tests/_util.random_events``)
and check, after every single event:

* per-order accounting: qty == filled + cancelled + expired + resting
* aggregate accounting: sum of per-order fills == 2 x traded volume
* each fill reduces opposite-side resting quantity by exactly its size
* full structural book invariants (``MatchingEngine.check_invariants``)

and, at the end, that every fill and the whole book match an independent
brute-force reference implementation exactly.
"""

from __future__ import annotations

import pytest

from src.events import Cancel, LimitOrder, MarketOrder
from src.matching_engine import MatchingEngine
from tests._util import BUY, SELL, book_state, fill_tuples, random_events
from tests.reference_engine import ReferenceEngine

SEEDS = range(60)


@pytest.mark.parametrize("seed", SEEDS)
def test_volume_conserved_after_every_event(seed):
    eng = MatchingEngine()
    submitted = 0
    for ev in random_events(seed, n=300):
        rest_before = {BUY: eng.book.total_qty(BUY), SELL: eng.book.total_qty(SELL)}
        res = eng.process(ev)
        traded = sum(f.qty for f in res.fills)
        rest_after = {BUY: eng.book.total_qty(BUY), SELL: eng.book.total_qty(SELL)}
        if isinstance(ev, (LimitOrder, MarketOrder)):
            submitted += ev.qty
            opp = ev.side.opposite
            assert rest_before[opp] - rest_after[opp] == traded
            added = rest_after[ev.side] - rest_before[ev.side]
            if isinstance(ev, LimitOrder):
                assert added == ev.qty - traded
            else:
                assert added == 0
                assert eng.orders[ev.order_id].expired == ev.qty - traded
        elif isinstance(ev, Cancel):
            assert traded == 0
        eng.check_invariants()

    recs = eng.orders.values()
    resting = eng.book.total_qty(BUY) + eng.book.total_qty(SELL)
    total_filled = sum(r.filled for r in recs)
    assert submitted == total_filled + sum(r.cancelled + r.expired for r in recs) + resting


@pytest.mark.parametrize("seed", SEEDS)
def test_matches_reference_implementation(seed):
    events = random_events(seed, n=300)
    eng, ref = MatchingEngine(), ReferenceEngine()
    for ev in events:
        eng.process(ev)
        ref.process(ev)
    assert fill_tuples(eng) == ref.fills
    assert book_state(eng) == ref.book_state()


def test_random_streams_actually_exercise_the_hard_cases():
    """Guard against the fuzzer silently becoming too gentle to be useful."""
    multi_level = partial_rest = partial_cancel_ok = crossing_limits = expired = 0
    for seed in SEEDS:
        eng = MatchingEngine()
        for ev in random_events(seed, n=300):
            res = eng.process(ev)
            if len({f.price for f in res.fills}) > 1:
                multi_level += 1
            if isinstance(ev, LimitOrder) and res.fills:
                crossing_limits += 1
                if ev.order_id in eng.book:
                    partial_rest += 1
            if isinstance(ev, Cancel) and ev.qty is not None and res.accepted:
                partial_cancel_ok += 1
            if isinstance(ev, MarketOrder) and eng.orders[ev.order_id].expired:
                expired += 1
    assert min(multi_level, partial_rest, partial_cancel_ok, crossing_limits, expired) >= 20
