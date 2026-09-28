# PROJECT.md — Simplified Limit Order Book Simulator & Liquidity Event Study

> **Status:** v1.0.0 complete. See `CHANGELOG.md`; findings are in
> `DECISIONS.md` ADR-004 and ADR-005.
> **Owner:** mateeniqbal3
> **Track:** Quant Finance (standalone — not tied to any academic
> semester/summer phase, not part of the RTP/Fulbright thesis narrative,
> and not dependent on `lob-alpha-engine`, `stat-arb-optimizer`,
> `pairs-trading-honest-costs`, or `vol-forecast-model-comparison` — this
> is its own independent project, though it shares those projects' $0-
> budget and honesty-first conventions)
> **Repo:** `lob-simulator`
> **License:** MIT
> **Purpose:** the most substantial engineering project in the quant
> track. Its value is not a trading signal — it's building a genuinely
> working piece of market microstructure infrastructure (a price-time
> priority matching engine with real queue-position tracking) and using
> it to run a liquidity event study. The point is to show real research
> interest rather than a portfolio checklist, and that distinction is
> protected throughout (see §2).

This is the canonical specification. Where it is ambiguous, the most
reasonable engineering decision is made and recorded in `DECISIONS.md`.

---

## 1. Purpose

Build a simplified but genuinely functional limit order book simulator —
implementing real price-time priority matching, queue position tracking,
and order lifecycle (submit, partial fill, full fill, cancel) — then use
it to run a liquidity event study: how does book liquidity (depth, spread,
resilience) behave before, during, and after a simulated stress event?
The simulator itself, not any single result it produces, is this
project's primary engineering deliverable.

## 2. What this project is and isn't — protect this distinction throughout

**This is a methodology demonstration built on synthetic order flow, not
a historical market event study**, unless real tick data genuinely
supports one (see §5). This distinction must be stated plainly and
prominently everywhere the project is described — README, code comments,
any figure caption — not softened into language that could be read as
claiming a real historical finding. Concretely:

- If the primary study runs on synthetic order flow with a deliberately
  injected liquidity shock (the default path — see §5), call it exactly
  that: a controlled, designed stress scenario used to validate that the
  simulator's liquidity metrics behave the way market microstructure
  theory predicts they should — not "what happened in the market on
  [date]."
- If a free real-data sample (e.g. LOBSTER's free tier) is used at all,
  it should be clearly scoped as a validation/calibration check on the
  simulator's mechanics (does the engine correctly reproduce basic
  stylized facts of a real book?), not stretched into a full event study
  if the sample's size, depth, or ticker coverage can't actually support
  one. Say explicitly what the free sample can and cannot support.
- The value of this project to a reader is the demonstrated engineering
  (a correct matching engine, correct queue mechanics) and demonstrated
  research judgment (knowing what a given dataset can and cannot honestly
  support), not a specific dramatic finding. A well-built simulator with
  an honestly-scoped synthetic study is a stronger portfolio piece than
  an overstated claim about real market behavior from insufficient data.

## 3. Problem Statement

Implement a limit order book matching engine that correctly enforces
price-time priority, tracks each resting order's queue position, and
processes limit orders, market orders, and cancellations realistically.
Use the simulator to construct a liquidity event study: inject a
controlled stress scenario (e.g. a burst of aggressive one-sided order
flow, or a sudden volatility increase in the order arrival process) and
measure how standard liquidity metrics (spread, depth at various levels,
resilience/recovery time) evolve before, during, and after the event.

## 4. Success Criteria (Definition of Done)

- [x] Matching engine implemented: correct price-time priority across
      multiple price levels, correct partial-fill handling, correct
      cancellation logic
- [x] Queue position tracking implemented and verifiably correct (a
      resting order's position in its price level's queue is tracked
      accurately as other orders arrive, fill, and cancel ahead of it)
- [x] Order flow generator implemented: a documented stochastic model for
      limit order arrivals, market order arrivals, and cancellations (see
      §6) — simple and clearly documented is preferred over an elaborate
      undocumented one
- [x] Data path resolved per §5 (synthetic primary; the real-data
      validation check was attempted, and the free sample turned out to
      need an account application — see ADR-003)
- [x] Liquidity event study implemented: a controlled stress scenario
      injected into the order flow, with before/during/after measurement
      of spread, multi-level depth, and resilience (time-to-recovery of
      pre-event liquidity levels)
- [x] **Naive-vs-realistic comparison** (this project's adaptation of the
      required gross/net comparison — see §9): simulated fill outcomes
      under a naive "instant fill at posted price, no queue" assumption
      vs. the actual price-time-priority/queue-aware simulation, shown
      side by side, demonstrating how much the naive assumption overstates
      achievable execution quality
- [x] Explicit bias-control section per §8
- [x] Honest "what didn't work / limitations" section
- [x] README structured per §10
- [x] Verification tests confirming the matching engine's correctness
      (not just that it runs) — see §11
- [ ] CI pipeline (lint + test) — workflow written and passing locally;
      it becomes "green" only once the repository is pushed and the
      workflow has run on GitHub. Docker was not added (see §12).

## 5. Data Path — Synthetic Primary, Real Data as an Optional Validation Check

**Budget constraint: $0**, same as every other repo in this quant track.

- **Primary path (required):** synthetic order flow generated by this
  project's own documented stochastic order-arrival model (§6), including
  a deliberately injected liquidity-shock scenario. This is the dataset
  the required liquidity event study (§4) runs on, and it is sufficient
  and appropriate for this project's actual deliverable — see §2.
- **Optional secondary path:** attempt LOBSTER's free sample data (a
  handful of trading days, limited tickers and depth) purely as a
  validation/calibration check — e.g. confirming the simulator's spread
  and depth metrics, computed on real order flow fed through the same
  engine, look qualitatively sane relative to known stylized facts of
  real limit order books. Do not attempt to force this limited sample
  into a full before/during/after event study — if the sample doesn't
  contain a genuine, identifiable stress event with adequate surrounding
  context, say so and keep this path scoped to validation only.
- Document whichever path(s) were actually used, and exactly what each
  one supports, in `data/dataset_manifest.json` and `DECISIONS.md`.

## 6. Order Flow Model (documented, simple, sufficient)

A simple, clearly documented stochastic model is preferred over an
elaborate one that's hard to verify. At minimum:
- Limit order arrivals: a Poisson (or similar documented) arrival process
  across price levels near the current best bid/ask
- Market order arrivals: a similar documented arrival process, sized
  reasonably relative to typical resting depth
- Cancellations: a documented probability of cancellation per unit time
  for resting orders
- **The injected event**: a clearly parameterized, documented change to
  one or more of the above (e.g. a burst of one-sided market order
  arrivals, or a temporary spike in the market order arrival rate) that
  constitutes the "stress scenario" for the event study

## 7. Liquidity Metrics

- Bid-ask spread over time
- Depth at multiple price levels (top-of-book and several levels deep)
- Resilience: time for spread/depth to return to pre-event levels after
  the injected shock ends

## 8. Bias Controls (named explicitly)

- **Look-ahead bias**: any metric computed "as of" a simulated time T
  must use only order book state as of T — verify this is structurally
  guaranteed by the simulator's event-driven design (state only updates
  when processing events in time order), not just assumed
- **Survivorship bias**: not directly applicable to a synthetic single-
  book simulation in the traditional sense, but if any real-data
  validation sample is used (§5), note explicitly that free real-data
  samples are typically drawn from currently-liquid, large-cap
  instruments, which is a form of selection that should be disclosed
- **Multiple-testing bias**: if multiple event-injection parameterizations
  or multiple random seeds were tried before selecting the one reported,
  disclose how many, same discipline as every other repo in this track

## 9. Required Comparison — Naive Fill Assumption vs. Queue-Aware Simulation

This project's adaptation of the "with/without transaction costs"
requirement (documented here so the substitution rationale is explicit,
per this track's established pattern in `vol-forecast-model-comparison`):
a trading-strategy P&L comparison doesn't apply to a market microstructure
simulator, so the equivalent honesty mechanism is comparing execution
quality under two assumptions:

| | Naive (instant fill, no queue) | Realistic (price-time priority + queue) |
|---|---|---|
| Fill rate | | |
| Average fill price vs. posted price | | |
| Effective spread realized | | |

Report this side by side and discuss the mechanism concretely (e.g. "at
the back of a deep queue during the injected stress event, X% of orders
that would fill instantly under the naive assumption did not fill at all
before being cancelled or repriced"). The filled-in version is in
`docs/results_comparison.md`.

## 10. Required README Structure

1. Clear problem statement and the mechanism/hypothesis being tested (what
   is the liquidity event study actually testing, and why would the
   injected scenario be expected to move liquidity metrics the way
   theory predicts?)
2. Methodology section explicitly naming the bias controls (§8)
3. Results shown side by side: naive fill assumption vs. queue-aware
   simulation (§9) — this project's adapted equivalent of gross-vs-net
4. An honest "what didn't work / limitations" section, framed as a
   positive signal of rigor
5. Explicit statement of what the study is (synthetic methodology
   demonstration) and is not (a real historical market event finding),
   per §2

## 11. Matching Engine Verification (this project's most important tests)

Because the entire project rests on the matching engine being genuinely
correct, `tests/` must include, at minimum:
- A test confirming strict price priority (a better-priced order fills
  before a worse-priced one at the same time)
- A test confirming strict time priority within a price level (earlier
  orders at the same price fill before later ones)
- A test confirming partial fills correctly update remaining quantity and
  preserve queue position for the remainder
- A test confirming cancellations correctly remove an order and do not
  affect other orders' queue positions incorrectly
- A test confirming no simulated event uses information from a
  future timestamp (the look-ahead check from §8)

These are in `tests/test_matching_engine.py`. Further coverage (volume
conservation, differential testing, bug reintroduction) is described in
`docs/engine_correctness.md`.

## 12. Tech Stack

Python · NumPy · pandas · matplotlib · pytest (and ruff for linting).
Deliberately minimal — this project's substance is the matching engine's
correctness and the event study's design, not framework sophistication.
Docker is optional: include a lightweight `Dockerfile` only if it
meaningfully aids reproducibility, and do not treat it as required for
this project's Definition of Done. (None was added. Results depend only
on seeded NumPy draws, and `results/run_metadata.json` records the
library versions used.)

## 13. Repository Structure

```
lob-simulator/
├── PROJECT.md, TASKS.md, IMPLEMENTATION_PLAN.md, ARCHITECTURE.md,
│   DECISIONS.md, CHANGELOG.md, README.md, LICENSE
├── requirements.txt, pyproject.toml, .gitignore
├── .github/workflows/ci.yml
├── src/
│   ├── events.py            # typed events (limit, market, cancel)
│   ├── order_book.py        # book state: price levels, FIFO queues per level
│   ├── matching_engine.py   # price-time priority matching, order lifecycle, fills
│   ├── order_flow.py        # stochastic arrival/cancellation model, section 6
│   ├── event_injection.py   # the controlled stress scenario, section 6
│   ├── simulation.py        # replay an event log; as-of-T sampling
│   ├── metrics.py           # spread, depth, resilience, section 7
│   ├── event_study.py       # before/during/after analysis with controls
│   └── naive_fill.py        # naive vs. price-touch vs. queue-aware fills, section 9
├── tests/                   # engine correctness (section 11) and everything else
├── scripts/
│   ├── run_simulation.sh    # tests -> bug-reintroduction check -> full study
│   ├── run_study.py         # the study itself; writes results/
│   └── mutation_check.py    # confirms the engine tests catch injected bugs
├── results/                 # every reported number (CSV/JSON) and figure
├── notebooks/01_event_study.ipynb
├── data/
│   ├── dataset_manifest.json
│   ├── raw/                 # gitignored; unused (no real data obtained)
│   └── processed/           # gitignored; per-probe detail written by the study
├── docs/
│   ├── engine_correctness.md
│   ├── results_comparison.md     # section 9's naive-vs-realistic table
│   └── liquidity_event_study.md  # the full before/during/after findings
└── paper/writeup.md
```

The optional `src/data_loader.py` for LOBSTER data was not written,
because no real data could be obtained (ADR-003). ADR-006 explains the
two modules added beyond the original layout.

## 14. Constraints & Guardrails

- $0 data constraint
- Never describe a synthetic study's findings using language that implies
  a real historical market event, per §2
- The matching engine's correctness tests (§11) are non-negotiable — a
  liquidity event study built on an unverified matching engine is not
  credible regardless of how interesting its results look
- Disclose the number of event-parameterizations/seeds tried, per §8
- Docker is optional, not required — do not treat its absence as
  incomplete

## 15. Definition of Done

See `TASKS.md`. At the project level: all boxes in §4 checked, matching
engine correctness verified by the tests in §11, the naive-vs-realistic
comparison (§9) reported honestly, the synthetic-vs-real-data distinction
(§2) stated plainly throughout, README structured per §10, CI green.
