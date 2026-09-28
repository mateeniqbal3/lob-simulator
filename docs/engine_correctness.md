# Engine Correctness Verification

Every later result in this repository depends on the matching engine
enforcing price-time priority correctly (`PROJECT.md` §11). This page
records how that was verified and what is **not** covered.

Reproduce:

```bash
pytest tests/ -v                              # full suite
python scripts/mutation_check.py --markdown   # the bug-reintroduction table below
```

## What is tested

| Property | Where | How |
|---|---|---|
| Price priority | `test_matching_engine.py::test_price_priority`, `test_matching_priority.py` | hand-built books; better price trades first regardless of arrival order; marketable limits walk levels best-first and stop at their limit |
| Time priority | `test_matching_engine.py::test_time_priority_within_level`, `test_matching_priority.py` | FIFO within a level, including exact timestamp ties (arrival sequence decides) and time priority at every level while walking the book |
| Partial fills keep queue position | `test_matching_engine.py::test_partial_fill_preserves_queue_position` | partially filled order stays at the front; new arrivals go behind it; size reductions (partial cancels) also keep priority |
| Cancellation | `test_matching_engine.py::test_cancellation_correctness`, `test_order_book_consistency.py` | removes exactly the remaining quantity; other orders' ranks and quantity-ahead shift correctly; repeated, post-fill and unknown cancels are rejected with no side effects |
| No look-ahead (engine) | `test_matching_engine.py::test_no_lookahead` | out-of-order events are refused with state unchanged; state after k events equals a fresh replay of only those k; replacing the future leaves past fills unchanged |
| No look-ahead (simulation) | `test_simulation.py`, `test_order_flow.py::test_future_schedule_cannot_change_the_past` | a sampled snapshot at T equals a replay truncated at T; an event scheduled at T changes nothing before T |
| Volume conservation | `test_matching_volume_conservation.py` | 60 seeded adversarial random streams; after **every** event, opposite-side resting quantity falls by exactly the traded quantity and per-order `qty = filled + cancelled + expired + resting` holds |
| Agreement with an independent implementation | `test_matching_volume_conservation.py::test_matches_reference_implementation` | on the same 60 streams, every fill (aggressor, resting order, price, size) and the full final book match `tests/reference_engine.py`, a brute-force matcher that shares no code with `src/` |
| Book invariants, never crossed | `test_order_book_consistency.py`, `OrderBook.check_invariants` | sorted price index, no empty levels, level totals equal sums of orders, each order in exactly one queue, FIFO sequence increasing, not crossed; checked after every event in the randomized tests |
| Lifecycle and edge cases | `test_matching_partial_fills.py`, `test_order_book_consistency.py` | empty book, one-sided book, market orders larger than the book (remainder expires), repeated market orders, extreme quantities (10¹²), invalid quantities, non-integer prices and duplicate ids raise |

The random streams use a narrow price band, so many limit orders are
marketable. They also include frequent exact timestamp ties, market
orders up to 4× typical depth, and partial, full and unknown cancels.
`test_random_streams_actually_exercise_the_hard_cases` fails if the
generator stops producing enough multi-level sweeps, partially filled
resting remainders, accepted partial cancels, marketable limits or
expired market orders.

At the time of writing, the six engine test files (`test_matching_*.py`,
`test_order_book*.py`) contain 200 passing tests; the full
suite has 223.

## Bug-reintroduction check

`scripts/mutation_check.py` copies `src/` and `tests/` to a temporary
directory and injects one targeted bug at a time. It then runs the
engine suite and records whether it failed, and whether the test
written for that property was among the failures. The unmutated copy
must pass first. Output of the latest run:

| Injected bug | Suite fails | Targeted test fails | Failing tests |
|---|---|---|---|
| Price priority: best bid taken as the LOWEST bid | yes | yes (`test_matching_engine.py::test_price_priority`) | 12 |
| Price priority: best ask taken as the HIGHEST ask | yes | yes (`test_matching_engine.py::test_price_priority`) | 12 |
| Time priority: LIFO within a level (newest order trades first) | yes | yes (`test_matching_engine.py::test_time_priority_within_level`) | 13 |
| Partial fill sends the remainder to the back of the queue | yes | yes (`test_matching_engine.py::test_partial_fill_preserves_queue_position`) | 7 |
| Cancel also bumps the new front-of-queue order to the back | yes | yes (`test_matching_engine.py::test_cancellation_correctness`) | 7 |
| Cancel leaves the order's quantity counted in the level total | yes | yes (`test_matching_engine.py::test_cancellation_correctness`) | 5 |
| Cancel of a non-resting order is accepted (double cancel) | yes | yes (`test_matching_engine.py::test_cancellation_correctness`) | 1 |
| No out-of-order guard (engine accepts events from the past) | yes | yes (`test_matching_engine.py::test_no_lookahead`) | 1 |
| Volume: maker credited with double the traded quantity | yes | yes (`test_matching_volume_conservation.py::test_volume_conserved_after_every_event`) | 13 |
| Volume: taker overfilled by one share on multi-order sweeps | yes | yes (`test_matching_volume_conservation.py::test_volume_conserved_after_every_event`) | 10 |
| Volume: partial fill does not reduce the level total | yes | yes (`test_matching_volume_conservation.py::test_volume_conserved_after_every_event`) | 9 |
| Trade executes at the aggressor's limit, not the resting price | yes | yes (`test_matching_priority.py::test_trade_price_is_resting_price_not_aggressor_limit`) | 5 |
| Marketable limit stops matching one level early (strict inequality) | yes | yes (`test_matching_engine.py::test_price_priority`) | 7 |
| Size reduction (partial cancel) sends the order to the back | yes | yes (`test_matching_engine.py::test_partial_fill_preserves_queue_position`) | 4 |
| Market order remainder silently counted as filled | yes | yes (`test_matching_partial_fills.py::test_market_order_larger_than_book_expires_remainder`) | 7 |

15/15 mutations were caught by their targeted test. ("Failing tests"
counts distinct test functions; parametrized cases count once.)

## Known coverage gaps (stated honestly)

- **Two properties rest on a single test each.** The double-cancel and
  out-of-order-event mutations are each caught by exactly one test. They
  are caught, but a later edit that weakens either test would leave the
  property unguarded.
- **15 mutations are a sample, not a proof.** They are the bugs judged
  most likely and most damaging. The mutation tool is hand-written, so
  it is not an exhaustive tool such as `mutmut`, and bugs outside this
  list may exist.
- **Random tests use seeded streams, not `hypothesis`** (ADR-007).
  Failures would not be shrunk to a minimal example, and the stream
  generator's distribution bounds what gets explored. For example, order
  sizes are 1–10 in the fuzz streams and 100-share lots in the study.
- **Features the engine does not have are not tested.** There are no
  hidden or iceberg orders, auctions, self-trade prevention, order
  modification other than size reduction, pro-rata matching, multiple
  venues or latency. The engine is simplified by design (see README
  limitations).
- **No real-data check.** The engine has never been run against real
  exchange messages (ADR-003), so agreement with a real venue's matching
  is untested.
