# IMPLEMENTATION_PLAN.md — lob-simulator

Standalone quant-track project, self-paced. This is the most substantial
engineering project in the small-project quant tier — budget roughly
**10-12 hrs/week**, higher than `pairs-trading-honest-costs` or
`vol-forecast-model-comparison`, reflecting the real complexity of a
correct matching engine.

## Week 1: Setup + Order Book Structure
- Phase 0, Phase 1
- Milestone: order book data structure supports add/remove/query
  operations correctly

## Week 2–3: Matching Engine — do not rush this
- Phase 2
- This is the project's foundation. Budget real time for getting all five
  correctness tests in `PROJECT.md` §11 genuinely passing, not just
  written. A subtly incorrect matching engine invalidates every later
  result.
- Milestone: all five matching-engine correctness tests pass

## Week 4: Order Flow Model
- Phase 3
- Milestone: order flow generator produces statistically sane output

## Week 5: Event Injection
- Phase 4
- Milestone: stress scenario parameterized and documented BEFORE the full
  study runs

## Week 6: Data Path Resolution
- Phase 5
- Milestone: synthetic path confirmed working; LOBSTER validation attempt
  (if pursued) honestly scoped in `DECISIONS.md`

## Week 7: Liquidity Metrics
- Phase 6
- Milestone: spread, depth, and resilience metrics computing correctly

## Week 8: Naive-vs-Realistic Comparison
- Phase 7
- Milestone: `docs/results_comparison.md` complete with a real mechanistic
  explanation, not just numbers

## Week 9: Liquidity Event Study
- Phase 8
- Milestone: full before/during/after study complete, framed per
  `PROJECT.md` §2

## Week 10: CI (+ optional Docker)
- Phase 9
- Milestone: CI green

## Week 11–12: Writeup
- Phase 10
- Milestone: writeup complete

## Week 13: Documentation Polish + Final Framing Review
- Phase 11
- Milestone: the explicit synthetic-vs-real-data language review (last
  item in Phase 11) is completed, not skipped — this is this project's
  equivalent of the honesty reviews in every other repo in this track

## Dependency Notes

- Do not proceed past Phase 2 until all five matching-engine correctness
  tests genuinely pass. Every later phase (order flow, event injection,
  metrics, the naive-vs-realistic comparison, the event study itself)
  depends on the engine being correct — debugging a subtle matching bug
  discovered in Week 9 would be far more costly than getting Phase 2 right
  the first time.
- Phase 4's event parameterization must be decided and documented before
  Phase 8's full study runs — choosing the event design after seeing which
  one produces the most dramatic result would be a form of the
  multiple-testing bias this project is supposed to guard against.
- Phase 5 (data path) can run in parallel with Phase 6 (metrics) if useful,
  since the LOBSTER validation check is optional and doesn't block the
  primary synthetic study.
