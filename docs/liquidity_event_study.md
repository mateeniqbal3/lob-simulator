# Liquidity Event Study — Findings

> **What this is:** a controlled experiment on synthetic order flow. A
> designed, one-sided burst of market sell orders is injected into a
> zero-intelligence order-flow model, and the simulated book's liquidity
> is measured around it. **It is not a study of any real market event.**
> No real data was used (DECISIONS.md ADR-003).

Reproduce with `python scripts/run_study.py`. Tables are in
`results/event_study_*.csv` and `results/robustness_grid.csv`, figures in
`results/figures/`.

## Event scenario (fixed before any stressed run: ADR-002)

- **Order flow:** the ADR-001 baseline. Per side, 1.0 limit orders/s and
  0.20 market orders/s; each resting order is cancelled at 0.05/s.
- **Stress:** the sell market-order rate is multiplied by 5
  (0.20 → 1.00 /s) for 300 s starting at t = 3,600 s. Nothing else
  changes.
- **Windows:**
  - warm-up `[0, 1800)`, discarded;
  - pre `[1800, 3600)`;
  - event `[3600, 3900)`;
  - early post `[3900, 4200)`;
  - late post `[4200, 7200]`.
- **Replication:** 20 seeds (0–19). Each seed is also run without the
  event (control). The two runs are event-for-event identical before
  3,600 s, so stressed − control isolates the event's effect from that
  seed's noise.

## Spread, depth, and resilience: before / during / after

Per-seed effect = stressed − control window mean. The table shows the
median across 20 seeds, the IQR, and how many seeds have the predicted
sign.

| Metric | During event | Early post (first 5 min) | Late post |
|---|---|---|---|
| Spread (ticks) | **+1.18** (IQR 1.02–1.36), 20/20 | +0.04, 13/20 | −0.00, 8/20 |
| Best-bid depth (shares) | **−332** (IQR −408 to −277), 20/20 | +3, 9/20 | +2, 8/20 |
| Bid depth, best 5 levels (shares) | **−1,899** (IQR −2,045 to −1,709), 20/20 | −48, 10/20 | +1, 10/20 |
| Best-ask depth (no prediction) | −272 | +58 | −2 |
| Ask depth, best 5 levels (no prediction) | −1,057 | +36 | −4 |

In levels, the median spread was 2.45 ticks against 1.28 in control
during the event. Best-bid depth was 349 shares against 705, and
best-5-level bid depth 1,474 against 3,346.

![Mean across seeds](../results/figures/event_study_seed_mean.png)

*Figure: mean across the 20 seeds of spread and bid depth (10 s trailing
mean), stressed runs against no-event controls. Synthetic order flow
with a designed stress scenario, not a real market event. Seed 0's
single run is in `results/figures/event_study_seed0.png`.*

**Resilience** (ADR-002 definition). Recovery time is measured from the
end of the event to the first moment the trailing 30 s mean is back
within 10% of the run's own pre-event mean. The placebo applies the same
rule to the no-event control.

| Metric | After the event: median (IQR; max) | Placebo: median (IQR; max) | Censored |
|---|---|---|---|
| Spread | 27 s (19–39; 81) | 0 s (0–1; 53) | 0 / 20 |
| Best-bid depth | 54 s (23–80; 217) | 2 s (0–21; 111) | 0 / 20 |
| Bid depth, best 5 levels | 38 s (32–61; 154) | 0 s (0–49; 112) | 0 / 20 |

Things the headline numbers alone would hide:
- **Undefined spread:** in a median 6% of event-window samples the bid
  side was completely empty. The spread is undefined there, and those
  samples are left out of the spread mean, so +1.18 ticks *understates*
  the widening.
- **Price:** the mid fell a median 99.5 ticks (about 1%) during the event
  and did not come back. The model has no fundamental value, so what
  recovers is liquidity, not price.
- **Ask side:** it thinned too, although only bids were being hit. A
  likely but unverified reason is that new asks are placed relative to a
  falling best bid, so fresh ask levels keep forming below older ones.

## Does the finding match microstructure theory's prediction?

**Direction: yes.** A burst of one-sided aggressive flow widened the
spread and removed bid depth in every one of the 20 seeds, and at every
intensity and duration in the robustness grid.

**Recovery speed: no, and the reason is the model.** Median recovery is
under a minute after a 5-minute shock, and window means are back to
control within 5 minutes. Real-market resilience is usually argued to
depend on liquidity suppliers' behavior, for example withdrawing or
repricing after being run over (Foucault, Kadan & Kandel, 2005). This
model has none of that:
- limit orders keep arriving at the baseline rate during and after the
  shock;
- they are placed relative to the opposite quote, so a wide spread is
  refilled within seconds;
- resting orders live for a mean of 20 s, so the book forgets quickly.

The fast recovery is a property of zero-intelligence order flow. It is
not evidence that real books recover this fast. Testing that would need
endogenous liquidity supply, for example limit-order intensity that
falls after adverse flow. That is the most informative next step.

## Robustness grid (all 9 pre-specified cells; the primary is 5× / 300 s)

| Multiplier | Duration | Spread Δ during | Best-5 bid depth Δ during | Spread recovery (median) | Bid depth 1–5 recovery (median) | Bid side empty during event |
|---|---|---|---|---|---|---|
| 2× | 60 s | +0.31 | −357 | 0.5 s | 15 s | 0% |
| 2× | 300 s | +0.26 | −554 | 0 s | 6.5 s | 0% |
| 2× | 900 s | +0.25 | −456 | 12 s | 1 s | 0% |
| 5× | 60 s | +1.07 | −1,354 | 25.5 s | 52 s | 2% |
| **5×** | **300 s** | **+1.18** | **−1,899** | **27 s** | **37.5 s** | **6%** |
| 5× | 900 s | +1.19 | −1,975 | 28 s | 42.5 s | 8% |
| 10× | 60 s | +1.89 | −2,375 | 31.5 s | 59.5 s | 26% |
| 10× | 300 s | +2.09 | −2,795 | 28 s | 52 s | 32% |
| 10× | 900 s | +2.06 | −2,890 | 33.5 s | 53 s | 33% |

- **Scaling:** effects scale with intensity, not duration. A stronger
  burst depletes the book further, but a longer one doesn't, because
  replenishment keeps pace once the book has adjusted.
- **2× bursts:** recovery times are close to placebo noise (placebo
  medians 0–5 s).
- **10× bursts:** the bid side is empty for about a third of the event.
- **Recovery:** under a minute at the median in every cell.

## Number of parameterizations/seeds tried

- **Before the study (no stressed runs):** 7 order-flow calibration
  configurations, no-event only, on separate seeds 1000–1002 (ADR-001).
- **Event designs:** one primary scenario and one 9-cell robustness
  grid, all fixed in ADR-002 before the first stressed run. No other
  designs were run.
- **Seeds:** 20 (0–19), all reported, none dropped.
- **Pipeline runs:** one 2-seed smoke test and four full runs. Runs 2
  and 3 changed only fill-comparison diagnostics (ADR-008 addendum), and
  run 4 only a figure footnote. Every event-study number was identical
  across all four.
