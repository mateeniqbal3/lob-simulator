# DECISIONS.md — Architecture Decision Records

Format: ADR number, status, Context / Decision / Consequences.

Status values: `Proposed`, `Accepted`, `Superseded by ADR-00X`, `Rejected`.

---

## ADR-001: Order flow model parameters

**Status:** Accepted (2026-09-28)

**Context:** `PROJECT.md` §6 requires a simple, documented stochastic
model for limit/market order arrivals and cancellations.

**Decision:** A zero-intelligence model (see `src/order_flow.py` for the
full description), with these baseline parameters:

| Parameter | Value | Meaning |
|---|---|---|
| `limit_rate` | 1.0 /s per side | Poisson limit-order arrivals |
| `market_rate` | 0.20 /s per side | Poisson market-order arrivals |
| `cancel_rate` | 0.05 /s per resting order | exponential order lifetime (mean 20 s) |
| placement | `d` ticks from the opposite best quote, `P(d) ∝ d^-0.5`, `d = 1..10` | limit orders never cross |
| limit size | 100 × U{1..5} shares (mean 300) | |
| market size | 100 × Geometric(0.4) shares (mean 250) | |
| initial quotes | 9,999 / 10,001 ticks | the book builds up from empty during warm-up |

Prices are integer ticks. All randomness comes from one
`numpy.random.default_rng(seed)` per run.

**How these values were chosen (disclosed in full).** Calibration used
only no-event runs on reserved seeds 1000–1002, which are never used
for the study itself. The first three configurations tried (the initial
defaults `limit 1.0 / market 0.12 / cancel 0.02 / alpha 0.8`, plus
`1.5 / 0.15 / 0.015 / 0.8` and `1.0 / 0.10 / 0.03 / 0.8`) all produced
an implausibly deep, static book: the spread sat at 1 tick 98–100% of the
time, top-of-book depth was about 10× the mean market-order size, and the
mid moved only 2–10 ticks in 1.5 simulated hours. After seeing that, I
wrote down explicit targets before trying anything else:

1. mean spread between 1.2 and 3 ticks;
2. mean best-bid depth between 2× and 5× the mean market-order size;
3. both sides of the book non-empty more than 99.9% of the time;
4. a mid price that actually moves.

Four more configurations were then tried (7 in total):

| Config | limit / market / cancel / alpha | Mean spread | Best-bid depth ÷ mean MO | One side empty | Mid range |
|---|---|---|---|---|---|
| D (chosen) | 1.0 / 0.20 / 0.05 / 0.5 | 1.34 | 2.7× | 0.00% | 42 ticks |
| E | 1.0 / 0.25 / 0.08 / 0.5 | 1.68 | 2.0× | 0.31% | 67 |
| F | 1.0 / 0.30 / 0.10 / 0.3 | 2.28 | 1.6× | 1.14% | 118 |
| G | 1.2 / 0.25 / 0.06 / 0.5 | 1.36 | 2.6× | 0.00% | 48 |

(Averages over seeds 1000–1002, measured on `t ≥ 1800 s` of a 7,200 s run.)
D and G both meet all four targets; D was chosen for its rounder numbers
and lower event count. These comparisons used no stressed runs, so
calibration could not have been steered by event-study outcomes.

**Consequences:** The baseline book is liquid but not deep: a typical
market order consumes a third of the best level. The model has no
informed traders, no order-size clustering, no intraday seasonality and
no feedback from price moves to order-flow intensity. Every liquidity
result in this repository is conditional on this model (see README
limitations).

---

## ADR-002: Event injection parameterization (pre-specified before any stressed run)

**Status:** Accepted (2026-09-28). Recorded before any simulation with
the stress event was run; nothing in this ADR was changed afterwards.

**Context:** `PROJECT.md` §8 requires the scenario to be fixed in advance,
not tuned after seeing results.

**Decision:**

- **Mechanism:** sell-side market-order arrival rate × **5** (0.20 → 1.00 /s)
  for **300 s**. Everything else (buy-side market orders, limit-order
  arrival and placement, sizes, cancellations) stays at baseline.
  (`src/event_injection.py`, `StressScenario(start=3600, duration=300)`)
- **Why 5×, argued from ADR-001 parameters and not from outcomes:**
  under the burst, sell market-order volume is about 1.0 × 250 = 250
  shares/s. Buy limit inflow is about 1.0 × 300 = 300 shares/s, spread over
  10 price levels. So the burst takes liquidity at close to the rate the
  whole bid side receives it, and several times the rate at which the best
  levels are refilled. That is a heavy stress that should deplete the top
  of the bid side, but it does not mechanically empty the book. 2× is
  within ordinary fluctuations; 10× removes liquidity much faster than any
  plausible replenishment. Both are reported as robustness checks, not as
  the primary specification.
- **Timeline (seconds of simulated time):** warm-up `[0, 1800)` discarded;
  pre-event baseline `[1800, 3600)`; event `[3600, 3900)`; post-event
  `[3900, 7200]`.
- **Seeds:** the primary result uses **20 seeds, 0–19**. Each seed is run
  twice: with the event, and as a **no-event control** with the same seed.
  The event schedule restarts the random clock only at 3600 s, so the two
  runs are event-for-event identical before 3600 s (checked by
  `tests/test_simulation.py`). Seed 0 is used for illustrative figures,
  chosen in advance.
- **Primary metrics** (sampled every 1 s, as of the sample time):
  spread (ticks); best-bid depth (shares at the best bid); cumulative
  bid depth over the best 5 occupied levels. Ask-side counterparts and
  the mid price are reported as secondary, descriptive metrics.
- **Window summaries:** means over pre `[1800, 3600)`, event
  `[3600, 3900)`, early post `[3900, 4200)`, and late post `[4200, 7200]`.
  The event effect is (stressed − control) per seed. I report the median
  and interquartile range across the 20 seeds, and how many seeds show
  the predicted sign.
- **Resilience (recovery time):** baseline `B` = mean of the metric over
  the run's own pre-event window. Recovery time = the first sample time
  `t ≥ 3900` at which the trailing 30-second mean of the metric (samples
  in `(t − 30, t]`) is back within 10% of `B`: `≤ 1.1 B` for spread,
  `≥ 0.9 B` for depth. The measure is strictly backward-looking. If this
  never happens by 7,200 s, the recovery time is **censored** and
  reported as "> 3300 s". The same rule applied to the no-event control
  (a **placebo** recovery time) shows how much of the measured
  "recovery" is ordinary noise.
- **Hypotheses (from standard microstructure reasoning, to be tested, not
  assumed):** H1: spread is wider during the event than in control.
  H2: bid-side depth is lower during the event than in control. H3: both
  recover within a finite time after the event ends, and that time is
  longer than the placebo. No prediction is made for ask-side depth.
- **Robustness grid, also decided now; every cell is reported:**
  multiplier ∈ {2, 5, 10} × duration ∈ {60, 300, 900} s, on the same 20
  seeds. The primary specification is the (5, 300) cell. The other 8 cells
  are robustness checks and are not candidates for the headline result.

**Consequences:** With the headline fixed, the only freedom left after
seeing results is in how they are described. Those descriptions are held
to the numbers in ADR-005.

---

## ADR-003: Data path outcome — synthetic only; LOBSTER validation attempted but not obtainable at $0 without an account application

**Status:** Accepted (2026-09-28)

**Context:** `PROJECT.md` §5 makes real-data validation optional and
explicitly warns against stretching a thin free sample into more than it
can support.

**Decision:** The primary study is synthetic (ADR-001, ADR-002). I tried
the optional LOBSTER validation path on 2026-09-28: the historical
direct-download URLs for the free sample files
(`lobsterdata.com/info/sample/LOBSTER_SampleFile_*.zip`) now return the
site's single-page web app, not a data file. The site offers sample data
only through a trial-account application reviewed by LOBSTER staff (for
example, with proof of academic conference attendance). Registering an
account and submitting proof is an external account action that the
owner has to take personally. So no real data was obtained and
`src/data_loader.py` was **not** written: a loader that had never parsed
a real file would be untested code claiming a capability the project
doesn't have.

**Consequences:** Nothing in this repository has been checked against
real order-book data. The README can claim only that the engine enforces
price-time priority correctly (verified by tests) and that the synthetic
book has a spread, depth and mid-price behavior that meet the stated
calibration targets. It cannot claim to reproduce real-market stylized
facts. If a LOBSTER sample is obtained later, the plan in `PROJECT.md` §5
still applies: replay its message file through the same
`MatchingEngine` and compare the rebuilt book with LOBSTER's orderbook
file. A useful and cheap check would be how often the engine picks the
same resting order the exchange reported as executed. Use it for
validation only, unless the sample happens to contain a clearly
identifiable stress episode with enough surrounding data.

---

## ADR-004: Naive-vs-realistic comparison finding

**Status:** Accepted (2026-09-28). All numbers come from `results/` as
written by `scripts/run_study.py`.

**Context:** This is this project's adapted equivalent of the gross-vs-net
comparison. See `PROJECT.md` §9; the methodology was fixed beforehand in
ADR-008.

**Decision (finding):** The setup was 14,280 probe decisions: 20 seeds ×
357 times × buy and sell, 100 shares each, on the primary stressed flow.
23 decisions were skipped because the probe's side of the book was empty,
leaving 14,257 per assumption.

| | Naive (instant fill) | Price-touch, no queue | Queue-aware engine |
|---|---|---|---|
| Passive fill rate within 60 s | 100% | 94.8% | 86.9% |
| Avg. execution price vs. posted | 0.00 ticks | +0.43 ticks worse | +0.84 ticks worse |
| Effective spread, `2·side·(price − mid)` | −1.40 ticks (earned) | −0.59 ticks (earned) | **+0.26 ticks (paid)** |
| Median time to fill | 0 s | 3.3 s | 10.6 s |
| Markout: `side·(mid 60 s after decision − price)` | +0.73 ticks | +0.31 ticks | −0.13 ticks |

- **The sign flips.** Under the naive assumption a passive order earns
  1.40 ticks of effective spread. Run through the engine, it pays 0.26.
- **Decomposing the 13.1-point fill-rate gap:**
  - 5.2 points come from the price never reaching the posted level
    (naive → touch);
  - 7.9 points come from queue position alone (touch → queue).

  The effective-spread gap of 1.66 ticks splits about evenly:
  0.81 ticks from price reach and 0.85 from the queue.
- **Queue mechanism, from recorded queue state.** Queue-aware fill rate
  falls steadily with the shares already queued at the posted price
  when the probe joined:
  - under 200 shares ahead: 93.8%
  - 200–499: 90.1%
  - 500–999: 86.7%
  - 1,000–1,999: 82.3%
  - 2,000 or more: 76.4%

  Price-touch fill rates stay between 93% and 98% across the same
  buckets. 1,181 probes (8.7% of price-touch fills) traded at their
  price but never reached the front of the queue. Their median queue
  ahead was 900 shares, against 600 for probes that did fill.
- **During the stress event the gap concentrates on one side.**
  - Sell probes rest on the ask while market sells sweep the bid. They
    filled 43% of the time queue-aware, against 65% for touch and 100%
    naive.
  - Execution was +13.8 ticks worse than posted, and the effective spread
    was +24.5 ticks against the naive −2.4. The unfilled asks were
    stranded as the mid fell (median −99.5 ticks over the event), and
    cleanup sold into a much lower bid. The naive assumption instead
    books those orders as filled at the ask just before the fall
    (naive markout +20.9 ticks).
  - Buy probes in the same window filled 100% under all three
    assumptions, with a median 1.9 s queue-aware. The sweep clears the
    queue ahead almost at once. All three carry a −18.3 tick markout, so
    on this side the naive assumption is not what hides the adverse
    selection.

**Consequences:**
- In this model, a naive backtest of passive quoting would report spread
  capture where the queue-aware engine reports a small net cost.
- The overstatement comes in roughly equal parts from ignoring whether
  the price is reached and from ignoring queue position.
- The overstatement is largest on the side that benefits from a
  directional move, because those are exactly the fills a queue denies.

These are properties of this synthetic model and probe design (ADR-001,
ADR-008), not estimates for any real venue.

**Caveats (measured):**
- Inserting probes perturbs the book. Best bid or ask differs from the
  no-probe replay in 11.2% of 1 s samples (range 9.4–12.3% across seeds).
- 4.7% of probe decisions (667) saw a different best quote. Restricted
  to the 13,590 decisions posted at the same price in both replays, the
  results barely move: fill rates 87.1% / 95.1% / 100%; effective spread
  +0.28 / −0.57 / −1.36 ticks
  (`results/fill_comparison_overall_same_posted.csv`).
- The strategy's own earlier probes are 4.4% of the queue ahead.
- 14 cleanup market orders could not be completely filled, because that
  side of the book was empty.

---

## ADR-005: Liquidity event study finding

**Status:** Accepted (2026-09-28). All numbers come from `results/` as
written by `scripts/run_study.py`.

**Context:** The core research question. See `PROJECT.md` §3 and §7; the
design was fixed beforehand in ADR-002.

**Decision (finding):** Primary scenario: sell market orders × 5 for
300 s, 20 seeds. Effects are the per-seed (stressed − control)
difference in window means, reported as the median and IQR across seeds.

| Metric | During event (300 s) | First 300 s after | Rest of run |
|---|---|---|---|
| Spread (ticks) | **+1.18** (IQR 1.02 to 1.36); 20/20 seeds wider | +0.04; 13/20 wider | −0.00; 8/20 |
| Best-bid depth (shares) | **−332** (IQR −408 to −277); 20/20 seeds lower | +3; 9/20 lower | +2; 8/20 |
| Bid depth, best 5 levels (shares) | **−1,899** (IQR −2,045 to −1,709); 20/20 | −48; 10/20 | +1; 10/20 |

Pre-event differences are exactly 0: the two runs are identical before
3,600 s.
- **Magnitudes:**
  - median spread 2.45 ticks against 1.28 in control;
  - median best-bid depth 349 shares against 705 (about −50%);
  - best-5-level bid depth 1,474 against 3,346 (about −56%).
- **Undefined spread:** in a median 6% of event-window samples the bid
  side was completely empty, so the spread was undefined. Those samples
  are excluded from the spread mean, which therefore *understates* the
  widening.
- **Ask side (no prediction was made):** it also thinned during the
  event: best-ask depth −272 shares, best-5-level −1,057 shares. A likely
  but unverified reason is that sell limits are placed relative to a
  best bid that is falling fast. New asks keep forming at fresh, lower
  prices while earlier ask depth is left far above the market.
- **Price:** the mid fell a median 99.5 ticks during the event (about 1%)
  and did not revert. This zero-intelligence model has no fundamental
  value to revert to, so "recovery" here means recovery of liquidity, not
  of price.
- **Resilience:** these are the ADR-002 recovery times after the event
  ends, against the placebo, which applies the same rule to the control
  run. No run was censored.

| Metric | After the event: median (IQR; max) | Placebo: median (IQR; max) |
|---|---|---|
| Spread | 27 s (19–39; 81) | 0 s (0–1; 53) |
| Best-bid depth | 54 s (23–80; 217) | 2 s (0–21; 111) |
| Bid depth, best 5 levels | 38 s (32–61; 154) | 0 s (0–49; 112) |

- **Hypotheses:**
  - H1 (spread wider during the event) is supported, 20/20 seeds.
  - H2 (bid depth lower during the event) is supported, 20/20 seeds.
  - H3 (finite recovery, longer than the placebo) is supported, but the
    recovery is fast. A 5-minute shock is absorbed in under a minute at
    the median, and nothing is detectable in window means 5 minutes
    after the event.
- **Robustness grid** (`results/robustness_grid.csv`; all 9 cells
  reported):
  - During-event effects have the predicted sign in every cell and grow
    with intensity, not duration. The spread effect is +0.25 to +0.31
    ticks at 2×, +1.07 to +1.19 at 5×, and +1.89 to +2.09 at 10×. Best-5
    bid depth is −357 to −554 shares at 2× and −2,375 to −2,890 at 10×.
  - At 2× the recovery times (0–20.5 s median) are hard to tell apart
    from placebo noise.
  - At 10× the bid side is empty in 26–33% of event samples.
  - Median recovery never exceeded 34 s for spread or 60 s for depth in
    any cell.

**Disclosure of everything that was run (`PROJECT.md` §8):**
- The primary scenario and the 9-cell grid were fixed in ADR-002 before
  any stressed run. No other event designs were tried. All 20
  pre-specified seeds are reported, with none dropped.
- Before that there were 7 no-event calibration configurations on
  separate seeds (ADR-001), and a 2-seed smoke test of the pipeline.
- The full pipeline was run four times. Runs 2 and 3 followed changes to
  the fill-comparison *diagnostics* only (ADR-008 addendum), and run 4
  only reworded a figure footnote. Every pre-specified event-study and
  fill-comparison number was identical across the four runs.

**Consequences:** The direction of the effects matches basic
microstructure reasoning. A one-sided burst of aggressive orders
consumes the side it hits, widens the spread and moves the price. The
**speed of recovery does not** match what is commonly argued for real
markets, where liquidity suppliers can withdraw or reprice after being
run over. Models with strategic liquidity supply (e.g. Foucault, Kadan &
Kandel, 2005) make resilience depend on the traders' own behavior.

That discrepancy is built into this model. Limit-order arrival is
exogenous: it continues at the baseline rate throughout and after the
shock. Orders are placed relative to the opposite quote, so a wide
spread is refilled within seconds. Resting orders are cancelled after a
mean of 20 s, so the book forgets the shock quickly. The fast
resilience measured here is therefore a statement about this
zero-intelligence model, not evidence that real books recover in under
a minute. The natural extension is to make limit-order intensity
respond to recent adverse flow, and to measure how much slower recovery
becomes.

---

## ADR-006: One flat module layout (consolidating two conflicting scaffolds)

**Status:** Accepted (2026-09-28)

**Context:** The initial scaffold contained two parallel layouts with
overlapping responsibilities. One was the flat `src/*.py` layout specified
in `PROJECT.md` §13. The other, from an earlier draft of the
specification, had `src/engine/{events,order_book,matching}.py`,
`src/analysis/{event_study,fill_comparison,liquidity_metrics}.py` and
`src/data/{lobster_loader,synthetic_generator}.py`. The earlier draft
also left duplicate docs (`docs/event_study_results.md`,
`docs/fill_comparison_results.md`), a duplicate notebook
(`notebooks/01_event_study_exploration.ipynb`), a duplicate script
(`scripts/run_pipeline.sh`) and duplicate placeholder tests
(`tests/test_data_loader.py`, `tests/test_fill_comparison.py`). Those
files cross-referenced phases, sections and ADR numbers that don't match
the current `PROJECT.md`, `TASKS.md` or this file.

**Decision:** Keep the `PROJECT.md` §13 layout, which is canonical, and
delete the earlier-draft duplicates. Two small modules are added beyond
§13:

- `src/events.py`: the typed events, shared by the generator and the
  engine (the earlier draft's `engine/events.py`, moved).
- `src/simulation.py`: the replay loop and as-of-T sampling, which
  both analyses need.

`src/event_study.py` holds the before/during/after analysis. Useful
ideas from the earlier draft were kept:

- volume-conservation, priority, partial-fill and book-consistency test
  files (now real tests);
- `docs/engine_correctness.md`, including the "reintroduce the bug and
  confirm the test fails" requirement (now `scripts/mutation_check.py`);
- time-to-fill as a comparison metric.

**Consequences:** One module per responsibility; no dead stubs.

---

## ADR-007: Engine design and how correctness is verified

**Status:** Accepted (2026-09-28)

**Context:** `PROJECT.md` §11 makes the engine's correctness the
foundation of every later result.

**Decision:**

- **Data structures:** each price level is an `OrderedDict` (insertion
  order is time priority; cancelling one order is O(1)). Each side keeps
  a sorted price list for the best-price lookup. Partial fills and size
  reductions modify an order in place, so its position is preserved by
  construction.
- **Fail loudly:** the book refuses a crossing insert, a non-positive
  quantity or a duplicate id. The engine refuses an out-of-order
  timestamp, a non-integer price or an invalid quantity. Cancels of
  unknown, filled or already-cancelled orders are *rejected and counted*
  rather than raising, because in live flow a cancel can legitimately
  race a fill.
- **Verification in four layers:**
  1. hand-built tests of each property, including the five required by
     §11;
  2. seeded random adversarial streams: a narrow price band, so many
     orders are marketable; timestamp ties; oversized market orders;
     partial, full and unknown cancels. Full invariants are checked after
     every event;
  3. a differential test against a deliberately naive reference matcher
     (`tests/reference_engine.py`) that shares no code with `src/`;
  4. `scripts/mutation_check.py`, which injects 15 specific bugs and
     confirms each one is caught by the test written for it.

  I used seeded random streams instead of the `hypothesis` library,
  keeping the stack at the minimal list in `PROJECT.md` §12. Random
  streams don't shrink failures to minimal examples, which is the main
  thing `hypothesis` would add.

**Consequences:** See `docs/engine_correctness.md` for results and known
coverage gaps.

---

## ADR-008: Naive-vs-realistic comparison methodology (pre-specified before running it)

**Status:** Accepted (2026-09-28), recorded before the comparison was run

**Context:** `PROJECT.md` §9 asks for execution quality under an "instant
fill at posted price, no queue" assumption versus the queue-aware engine,
on identical order flow.

**Decision:**

- **Execution opportunities (probes):** every 15 s from 1,800 s to
  7,140 s, submit one 100-share buy at the current best bid and one
  100-share sell at the current best ask. Each joins the back of its
  queue. A probe stays live for up to 60 s. Anything unfilled at the
  deadline is cancelled and completed with a market order (the "cleanup"
  a real strategy committed to trading would need). If a probe's side of
  the book is empty at decision time, the probe is skipped and counted.
- **Order flow:** the ADR-002 primary scenario (5×, 300 s), seeds 0–19.
  The same background event log is used for every assumption.
- **Three fill assumptions on the same log:**
  1. **Naive (spec):** fills instantly and in full at the posted price.
  2. **Price-touch, no queue:** fills in full at the posted price the
     first time a background trade prints at or through the posted price
     within 60 s; otherwise cleanup at the opposite best quote at the
     deadline. This isolates the queue effect from the "price must be
     reached" effect.
  3. **Queue-aware (realistic):** the probe is actually inserted into the
     `MatchingEngine` behind every order already resting at its price
     and fills only through price-time priority; otherwise cleanup by a
     real market order.
- **Metrics per assumption, and by window (pre / event / post):**
  - passive fill rate;
  - average execution price vs. posted price (ticks, positive = worse);
  - effective spread `2 × side × (exec price − mid at decision)` in ticks
    (negative = spread earned);
  - time to fill.
  For the queue-aware run I also report the queue ahead at submission
  and fill rate by queue-ahead bucket. That is the direct evidence for
  (or against) the queue mechanism.
- **Identical-flow caveat, measured rather than assumed:** in the
  realistic run a probe can absorb part of a background market order
  that would otherwise have reached a background resting order. That can
  change a few later background events (for example, a background cancel
  targeting an order that has since filled gets rejected). The number of
  background fills and cancels that differ from the no-probe replay is
  reported alongside the results.

**Consequences:** The naive assumption's fill rate and price are 100% and
0 ticks by construction. That is exactly the claim under test, not a
finding.

**Addendum (2026-09-28, after the first full run): diagnostic change,
disclosed.** The first run measured background divergence as the
symmetric difference of background fill tuples. That counts every
changed fill twice and gives 59%. It also flagged mere size changes: once
a probe absorbs part of a market order, every later partial fill at that
level shifts. It said nothing about whether the book the three
assumptions face actually differs. It was replaced with three measures:

- a one-directional count (31.7% of background fills are not reproduced
  exactly, mostly size shifts);
- the share of 1 s samples where the best quotes differ (11.2%);
- each probe's own-probe share of its queue ahead (4.4%).

A sensitivity table was also added, restricted to decisions posted at
identical prices. None of the pre-specified metrics or probe rules
changed, and every number in the comparison tables was identical before
and after.
