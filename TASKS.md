# TASKS.md — lob-simulator

Ordered checklist, worked top to bottom, one commit per phase group.
`PROJECT.md` §2 and §11 come before Phase 2 (matching engine): the
engine's correctness is this project's foundation, and §2's honesty
framing applies to how every later result is described.

## Phase 0 — Setup

- [x] `.gitignore` (Python, data/raw, data/processed, .env, caches, local tooling)
- [x] `pyproject.toml`, `requirements.txt`
- [x] `LICENSE` (MIT, current year)
- [x] Folder structure per `PROJECT.md` §13 (earlier-draft duplicates removed: ADR-006)
- [ ] Init git repo and commit: "chore: initial project scaffold" (left to the owner)

## Phase 1 — Order Book Data Structure

- [x] `src/order_book.py`: bid/ask price levels, each a FIFO queue of resting orders
- [x] Add, remove, reduce-in-place, best bid/ask, depth by level, queue position
- [x] `tests/test_order_book.py`
- [ ] Commit: "feat: order book data structure"

## Phase 2 — Matching Engine (the critical phase)

- [x] `src/matching_engine.py`: limit orders, market orders, cancellations
      (full and size-reducing), strict price-time priority
- [x] Partial fills keep their original time priority
- [x] `tests/test_matching_engine.py` with all five `PROJECT.md` §11 tests
      passing, plus priority, partial-fill, volume-conservation,
      differential and consistency test files
- [x] Bug-reintroduction check: `scripts/mutation_check.py` (15/15 caught)
- [ ] Commit: "feat: matching engine with verified price-time priority"

## Phase 3 — Order Flow Model

- [x] `src/order_flow.py`, parameters calibrated and recorded (ADR-001)
- [x] `tests/test_order_flow.py`: rates, placement distribution, sizes,
      cancellation intensity, determinism, no-look-ahead
- [ ] Commit: "feat: stochastic order flow model"

## Phase 4 — Event Injection

- [x] `src/event_injection.py`
- [x] Parameterization recorded in `DECISIONS.md` ADR-002 before any stressed run
- [ ] Commit: "feat: liquidity stress event injection"

## Phase 5 — Data Path Resolution

- [x] Synthetic path confirmed end to end (`tests/test_simulation.py`)
- [x] LOBSTER free sample attempted: not available without a trial-account
      application (ADR-003); `src/data_loader.py` therefore not written
- [x] Outcome documented in `DECISIONS.md` ADR-003 and `data/dataset_manifest.json`
- [ ] Commit: "feat: data path resolved — see DECISIONS.md"

## Phase 6 — Liquidity Metrics

- [x] `src/metrics.py`: spread, multi-level depth, resilience (recovery time, censoring)
- [x] `tests/test_metrics.py`
- [ ] Commit: "feat: liquidity metrics (spread, depth, resilience)"

## Phase 7 — Naive-vs-Realistic Comparison

- [x] `src/naive_fill.py` (naive, price-touch, queue-aware; same event log)
- [x] Methodology fixed in ADR-008 before running
- [x] `docs/results_comparison.md` with the table and the mechanism
- [x] `tests/test_naive_vs_realistic.py`
- [ ] Commit: "feat: naive vs. queue-aware fill comparison"

## Phase 8 — Liquidity Event Study

- [x] Full study run (`scripts/run_study.py`, 20 seeds, stressed + control, 9-cell grid)
- [x] `docs/liquidity_event_study.md`, framed as a synthetic controlled scenario
- [x] Everything tried disclosed in `DECISIONS.md` ADR-005
- [ ] Commit: "feat: liquidity event study complete"

## Phase 9 — CI (and optional Docker)

- [x] `.github/workflows/ci.yml`: ruff, pytest, bug-reintroduction check
- [x] Docker not added (optional; see `PROJECT.md` §12)
- [ ] CI green on GitHub (requires the repository to be pushed)

## Phase 10 — Writeup

- [x] `paper/writeup.md`

## Phase 11 — Documentation Polish

- [x] `README.md` per `PROJECT.md` §10
- [x] `DECISIONS.md` filled with real decisions and findings
- [x] `CHANGELOG.md` v1.0.0 entry
- [x] Framing review of README, writeup, docs, figure captions and code
      comments for any language implying a real market event

## Definition of Done

All boxes checked, matching-engine correctness verified by the Phase 2
tests, naive-vs-realistic comparison reported honestly, the event study's
synthetic status stated plainly throughout, README structured per §10,
CI green. The remaining unchecked items all need the owner: making the
commits, pushing, and the first CI run.
