# ARCHITECTURE.md — lob-simulator

## 1. System Overview

An event-driven simulation. A stochastic order-flow generator produces
events (limit orders, market orders, cancellations) in time order. A
matching engine processes them one at a time, updating the order book and
recording fills. The liquidity event study and the naive-vs-realistic
comparison are both analyses of replays of that event log, not separate
systems.

## 2. Core Simulation Flow

```
src/order_flow.py  (+ src/event_injection.py schedule)
  Gillespie simulation of competing Poisson clocks:
  limit orders, market orders, cancellations.
  State-dependent: prices set relative to the current quotes,
  cancels pick among resting orders, so it runs its own engine
  and reads the book only as of "now".
        |
        v
  Event log: list[LimitOrder | MarketOrder | Cancel]   (src/events.py)
  deterministic given (parameters, schedule, seed)
        |
        v
src/simulation.py  replay(events, horizon, sample_interval, agents)
  fresh MatchingEngine; for each event in order:
    - take any samples / agent decisions due strictly before it
    - engine.process(event)
        |
        v
src/matching_engine.py + src/order_book.py
  - limit order  -> match against best opposite prices while it
                    crosses; the remainder rests at the back of its level
  - market order -> match best-first, walking levels; the remainder expires
  - cancel       -> remove (or reduce in place); others keep their position
  - refuses out-of-order timestamps (structural no-look-ahead)
        |
        v
  Fills + per-order lifecycle records + 1 s snapshots of the book
```

## 3. Analysis Flow

```
                      event log (one per seed and arm)
                 +------------------+-------------------+
                 v                                      v
   src/event_study.py                         src/naive_fill.py
   stressed vs. same-seed control             same stressed log replayed twice:
   snapshots -> src/metrics.py                 (a) no probes: naive + price-touch
   window means, recovery, placebo            (b) probes in the engine: queue-aware
                 |                                      |
                 v                                      v
        results/event_study_*.csv            results/fill_comparison_*.csv
        results/robustness_grid.csv           results/figures/fill_rate_by_queue_ahead.png
        results/figures/event_study_*.png
                 |                                      |
                 v                                      v
   docs/liquidity_event_study.md            docs/results_comparison.md
```

`scripts/run_study.py` drives all of it; `scripts/run_simulation.sh` runs
the tests and the bug-reintroduction check first.

## 4. Component Responsibilities

| Component | Responsibility | Does NOT do |
|---|---|---|
| `src/events.py` | Typed events; prices are integer ticks | Any logic |
| `src/order_book.py` | Book state: sorted price levels, FIFO queue per level, queue position, invariant checks | Matching |
| `src/matching_engine.py` | Price-time priority matching, fills, order lifecycle accounting, time-order guard | Generate order flow |
| `src/order_flow.py` | Baseline stochastic event stream | Analysis |
| `src/event_injection.py` | Rate multipliers during the event window | Matching |
| `src/simulation.py` | Replay a log; as-of-T snapshots; agent hook | Metric definitions |
| `src/metrics.py` | Spread/depth window means, trailing means, recovery time | Simulation |
| `src/event_study.py` | Stressed vs. control runs, effect and recovery tables | Plotting |
| `src/naive_fill.py` | Probe agent; naive, price-touch and queue-aware fills on the same log | Change the engine |

The engine contains no research assumptions: an analysis bug cannot
require touching `order_book.py` or `matching_engine.py`, and engine bugs
can be found with the engine tests alone.

## 5. Real Data

Had a LOBSTER sample been obtained (it was not: ADR-003), its message
file would have been replayed through the same `MatchingEngine` and
`OrderBook`. That is what would make it a validation of *this* engine
rather than an unrelated analysis.

## 6. Key Architectural Decisions (full rationale in DECISIONS.md)

- **Event-driven design as the structural guarantee against look-ahead
  bias.** The engine sees one event at a time and rejects any timestamp
  earlier than the last. Snapshots are taken in the replay loop before
  later events are processed. The generator restarts its random clock at
  schedule breakpoints, so a future event cannot change the past. Each
  of these is confirmed by tests (`test_no_lookahead`,
  `tests/test_simulation.py`,
  `test_future_schedule_cannot_change_the_past`).
- **Partial fills preserve time priority.** A partially filled order is
  reduced in place in its level's `OrderedDict`, so it keeps its queue
  position (ADR-007).
- **Same-seed controls.** Every stressed run has a no-event twin that is
  identical up to the event, so effects are differences, not comparisons
  with a noisy baseline (ADR-002).
- **Synthetic order flow as the only dataset.** See `PROJECT.md` §2 and
  §5, and ADR-003.
