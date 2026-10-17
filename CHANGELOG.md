# CHANGELOG.md

All notable changes to this project are documented here. Loosely follows
[Keep a Changelog](https://keepachangelog.com/).

## [1.1.0] — 2026-10-17 — Working paper

No change to the engine, the experiments or any recorded result.

### Added
- `paper/writeup.md` upgraded to a working paper: author affiliation,
  prose abstract, keywords and JEL codes, a related-work paragraph,
  three figures, an effective-spread definition under the fill table,
  data-availability and AI-use statements, and full references; built PDF
  `paper/writeup.pdf`
- `paper/make_figures.py`: paper and README figures from the committed
  outputs in `results/`
- `paper/build_pdf.py`: builds the PDF with pandoc and XeLaTeX
- README results chart and paper link; `CITATION.cff`

### Changed
- `pyproject.toml` version 0.1.0 → 1.1.0 (it had not been bumped for
  1.0.0); author name in `pyproject.toml` and `LICENSE` set to Muhammad
  Mateen Iqbal

---

## [1.0.0] — 2026-09-28 — Engine, study and writeup

### Added
- Order book (`src/order_book.py`): FIFO queue per price level, queue
  position, in-place reduction that keeps priority, invariant checker.
- Matching engine (`src/matching_engine.py`): price-time priority for
  limit orders, market orders, and full or size-reducing cancels. Also
  per-order lifecycle accounting, and rejection of out-of-order events.
- Engine verification:
  - the five `PROJECT.md` §11 tests;
  - priority, partial-fill and consistency test files;
  - volume conservation checked after every event on 60 adversarial
    random streams;
  - a differential test against an independent brute-force matcher;
  - `scripts/mutation_check.py`, where 15 of 15 injected bugs are caught
    by their targeted test.
- Zero-intelligence order-flow model (`src/order_flow.py`), calibrated on
  no-event runs (ADR-001).
- Sell-side market-order burst scenario (`src/event_injection.py`),
  pre-specified in ADR-002.
- As-of-T replay and sampling (`src/simulation.py`); spread, depth and
  recovery-time metrics (`src/metrics.py`).
- Event study with same-seed no-event controls, placebo recovery times
  and a 9-cell robustness grid (`src/event_study.py`). Findings are in
  ADR-005 and `docs/liquidity_event_study.md`.
- Naive, price-touch and queue-aware execution comparison on identical
  order flow (`src/naive_fill.py`). Findings are in ADR-004 and
  `docs/results_comparison.md`.
- `scripts/run_study.py` and `scripts/run_simulation.sh`; all reported
  numbers and figures are written to `results/`.
- CI: ruff, pytest and the bug-reintroduction check.
- `paper/writeup.md`, a filled-in README, and ADR-003 and ADR-006 to
  ADR-008.

### Changed
- Consolidated two conflicting scaffold layouts into the single
  `PROJECT.md` §13 layout, and removed the earlier-draft duplicate
  modules, docs, notebook, script and placeholder tests (ADR-006).
- Order-flow defaults changed from the first-draft values to the
  calibrated ones (ADR-001: market rate 0.12 → 0.20, cancel rate
  0.02 → 0.05, placement exponent 0.8 → 0.5).
- Fill-comparison divergence diagnostic replaced after the first full
  run. The original double-counted and measured the wrong thing. No
  pre-specified metric changed (ADR-008 addendum).

### Not done
- LOBSTER real-data validation: the free sample now requires a
  trial-account application (ADR-003). No `src/data_loader.py`.
- Docker (optional per `PROJECT.md` §12).

---

## [0.1.0] — Scaffold

### Added
- Repository structure
- `PROJECT.md`, `TASKS.md`, `IMPLEMENTATION_PLAN.md`, `ARCHITECTURE.md`,
  `DECISIONS.md` — full project specification, including the
  synthetic-vs-real-data honesty framing and the required matching-engine
  correctness tests, before any code was written
- MIT License
