"""Remaining gates — specifications, to be implemented in order.

Each is written as a spec first so that what the gate must do is fixed before
the result is known. Implement top to bottom; do not reorder to reach a
prettier waterfall.


integrity  (Gate.INTEGRITY)
---------------------------
Reuse the outlier machinery already built for fund-level anomaly detection and
point it at the equity panel. Isolation Forest over
(return, volume, |return|/trailing vol, price level, shares outstanding change),
plus deterministic rules for the failures a forest will not catch: unadjusted
split ticks, stale price runs, and zero-volume days carrying a nonzero return.
Materiality filter so a flagged cell only matters if it moves the decile
assignment. Output: share of signal-weighted exposure resting on flagged cells.
Kill the signal if the alpha is concentrated in them.

Why this gate is the differentiated one: an agentic strategy-sourcing pipeline
proposes signals faster than any human can sanity-check the data underneath
them. Data integrity is the gate that does not scale by hiring more reviewers.


raw  (Gate.RAW)
---------------
Long-short decile portfolio, monthly rebalance, equal-weight and
value-weight reported separately. Report both; headline the value-weight, since
equal-weight decile spreads on a text signal are usually a microcap story.


orthogonalize  (Gate.ORTHOGONALIZE)
-----------------------------------
Two passes, reported separately:
  1. time-series: regress the long-short return on FF5 + MOM (+ STR), report the
     HAC-corrected alpha. `quant/core/metrics/factor_regression.py` already does
     this -- reuse `regress_alpha_on_factors`.
  2. cross-sectional: neutralise the raw score to sector and to size/value/
     momentum *before* forming deciles, then re-run. This is the harder test and
     the one that matters: it asks whether the signal ranks stocks, or whether it
     ranks characteristics that already have names.
Surviving Sharpe = the sector- and factor-neutral version.


costs  (Gate.COSTS)
-------------------
Do not assume a cost. Solve for the breakeven: the per-side cost in bps at
which the surviving Sharpe hits zero, given realised turnover. Report
`breakeven_bps` next to a plausible range for the universe's liquidity band.
A signal with a 4bp breakeven on small caps has not survived; it has been
described more precisely.


dsr  (Gate.DSR)
---------------
`quant/core/metrics/deflated_sharpe.py` already implements PSR/DSR. The only
new rule here: `n_trials` and `trial_sharpe_variance` come from
`TrialLedger`, never from an argument the caller chooses. If the family has
fewer than two completed trials, this gate must REFUSE rather than deflate with
an assumed variance -- an unfalsifiable pass is worse than no gate.


pbo  (Gate.PBO)
---------------
Combinatorially Symmetric Cross-Validation (Bailey, Borwein, Lopez de Prado,
Zhu). Split the sample into S=16 blocks, take all C(16,8) train/test splits,
and report the fraction of splits where the in-sample-best configuration ranks
below median out of sample. PBO > 0.5 means the selection procedure has no
skill, whatever the reported Sharpe is.
"""
