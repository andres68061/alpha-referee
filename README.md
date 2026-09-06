# alpha-referee

**An agent can propose a hundred signals a day. This decides which ones are real.**

`alpha-referee` is a pre-registered replication harness for text-derived equity
signals. It takes a claim from a published paper, rebuilds the signal from SEC
filings on a point-in-time panel, and runs it through a fixed gauntlet that
reports how much of the headline Sharpe survives each honest correction.

The deliverable is not a strategy. It is a **scorecard**.

---

## The claim this repo is built around

> A deflated Sharpe ratio is only honest if `N` — the number of trials you ran —
> is honest. In every published backtest, `N` is a number the author chooses
> after the fact. Here `N` is read off an append-only, hash-chained trial ledger
> that is written *before* each run and cannot be understated without breaking
> the chain.

Everything else in this repo exists to make that sentence true and testable.

---

## The gauntlet

Each signal is scored once and reported as a decay waterfall, in this fixed
order. The order is pre-registered; it is not chosen to flatter a result.

| # | Gate | Question | Typical damage |
|---|------|----------|----------------|
| 0 | `pit` | Did we use the filing before it was public? | often fatal |
| 1 | `integrity` | Is the panel itself clean, or is the alpha a corporate-action artefact? | |
| 2 | raw | Long-short decile Sharpe, gross | headline number |
| 3 | `orthogonalize` | What survives after FF5 + momentum + sector? | |
| 4 | `costs` | Breakeven cost in bps vs realistic turnover | |
| 5 | `dsr` | Deflated Sharpe against the ledger's honest `N` | |
| 6 | `pbo` | CSCV probability of backtest overfitting | |

A signal that clears every gate gets `Verdict.SURVIVES`. Everything else records
*where* it died, which is the part that is actually informative.

---

## Signals implemented

Each is a published, named claim — not an invention — so replication failure is
a result rather than an excuse.

| Module | Claim | Source |
|---|---|---|
| `signals/lazy_prices.py` | Year-over-year 10-K text similarity predicts returns; firms that change their filing language underperform | Cohen, Malloy & Nguyen (2020), *Lazy Prices*, JF |
| `signals/lm_sentiment.py` | Finance-specific negative-word tone in MD&A predicts returns | Loughran & McDonald (2011), JF |
| `signals/risk_novelty.py` | Newly-appearing Item 1A risk language predicts returns | risk-disclosure literature |
| `signals/embeddings.py` | Sentence-embedding distance as a continuous replacement for (1) and (3) | — |

(4) exists so the lexicon and embedding formulations of the *same* economic
claim can be put through the identical gauntlet and compared. That comparison —
does the embedding version buy anything once both are deflated by an honest `N`?
— is the research question.

---

## Layout

    prereg/       hypothesis, falsifiers and expected effect size, committed before data
    corpus/       EDGAR 10-K/10-Q full text, stamped with filing acceptance datetime
    signals/      text -> cross-sectional score, one module per published claim
    referee/      the gates, in order
    trials/       append-only hash-chained ledger — every variant ever run
    report/       the decay waterfall
    docs/         method notes

## Data

Public only. SEC EDGAR full text (filing acceptance timestamps, not period-end
dates), Ken French factor library, CRSP-free price panel. No vendor or employer
data is used anywhere in this repository.
