# Build order — day 1

The point of today is to reach a *runnable gauntlet with one real signal in it*.
Not a good signal. A measured one.

---

## STATUS — built and tested, offline

    adapters/quant_lake.py   reads quant's lake: prices, returns, ADV, FF5, membership, sectors  DONE
    corpus/edgar.py          EDGAR client: CIK, full filing history, acceptanceDateTime, HTML->text  DONE
    corpus/fetch.py          universe -> filings -> text, resumable  DONE (needs network)
    trials/ledger.py         hash-chained trial ledger  DONE, 5 tests
    referee/verdict.py       Verdict + waterfall  DONE
    referee/gauntlet.py      ordered runner, missing gate is fatal  DONE, verified
    referee/pit.py           Gate 0  DONE
    referee/gates_todo.py    specs for gates 1-6  YOURS TO WRITE

    pytest -q  ->  8 passed

Two things surfaced while wiring the adapter, both worth keeping:

  * `fama_french_5.parquet` round-trips `date` as the pandas index but exposes
    it as a column in the arrow schema. `load_ff5` now accepts either.
  * `index_membership.parquet` records **GLD as an S&P 500 member from
    1996-01-02 to 1997-05-05**. GLD did not list until 2004, so that row is a
    reused-ticker collision, and taking membership at face value put a gold ETF
    in the top-20 by liquidity. `liquid_universe` now cross-checks
    `quoteType == "EQUITY"` and requires membership to overlap the study window.
    This is a small live example of the thesis: a universe bug manufactures
    alpha, and no amount of model quality catches it.

---

## 0. Start the corpus download — FIRST, it runs while you work

    python -m corpus.fetch --top-n 200 --start 2012-01-01 --end 2025-12-31

Both sandboxes I have block sec.gov, so this has to run on your machine. It is
resumable — everything caches by accession, so an interrupted run picks up.
Expect ~2,000-2,500 10-Ks and 20-40 min at 8 req/s.

The old plan for this step, for reference:

- Universe: reuse `quant/core/data/sp500_constituents.py` +
  `universe_filters.build_universe_filter()` so membership is survivorship-free.
  Start with the **top 200 by dollar volume, 2012–2025** — roughly 2,500 10-Ks.
  Full S&P 500 back to 2005 is ~9,000 filings; that is a weekend, not a day.
- Reuse `quant/core/data/sec/client.py` — CIK resolution, the fair-access
  User-Agent and rate limiting are already written.
- For each filing store: `cik, ticker, form, period_end, filing_date,
  **acceptanceDateTime**, primary_doc_url, raw_text`.
  **`acceptanceDateTime` is the field the whole PIT gate depends on.** It is in
  the submissions JSON. Do not drop it and do not substitute `filingDate`.
- Strip HTML to text once, cache to parquet under `corpus/text/`, keyed by
  accession number. Never re-download.
- Rate limit: 10 req/s. ~2,500 filings ≈ 15–25 min of wall clock. Let it run.

## 1. Trial ledger — already written  ✅

`trials/ledger.py`. Read it once. The contract is: **you never type an `N`
again.** Before any run, `ledger.record(Trial(...))`.

## 2. Wire the first signal — `signals/lazy_prices.py`  — 2 hrs

Cohen, Malloy & Nguyen (2020). For each firm-year, cosine similarity between
this 10-K and the previous one, on the Item 7 (MD&A) + Item 1A sections.
Low similarity = the firm changed its language = short.

- Section extraction is the fiddly part. Regex on the item headers, keep a
  `extraction_failed` flag rather than silently returning the whole document.
  Report the failure rate in the scorecard; it is a real caveat.
- Similarity: start with TF-IDF cosine on the raw sections. Do *not* start with
  embeddings — you want the lexicon baseline first so the embedding version has
  something to beat.
- Output contract: a dataframe with
  `ticker, signal_date, acceptance_datetime, score, extraction_failed`.
  `signal_date` is what you would have traded on; `acceptance_datetime` is
  ground truth. The PIT gate compares them.

## 3. Run the PIT gate and let it fail  — 30 min

`referee/pit.py` is written. Point it at your aligned frame.

**Deliberately run it once with the naive alignment** (signal dated at fiscal
period end, the way a careless replication would do it) and record the
lookahead percentage. Then fix the alignment and run again. That before/after
pair is the first real result in the repo and it belongs in the README.

## 4. Raw decile spread  — 2 hrs

Reuse `quant/core/backtest/` and `quant/core/signals/sector_neutral.py`.
Value-weighted long-short deciles, monthly rebalance. Report the Sharpe.
Expect it to be lower than the paper. That is fine and it is the point.

## 5. Orthogonalize  — 1 hr

`quant/core/metrics/factor_regression.regress_alpha_on_factors` already does the
FF5+MOM regression with HAC lags. Wire it in as `Gate.ORTHOGONALIZE`.

## 6. Stop. Write the waterfall.  — 30 min

`Verdict.waterfall()` prints. Paste it in the README under a heading called
**Result**. One signal, four gates, honest numbers.

That is a shippable day.

---

## Days 2–5, in priority order

1. `Gate.COSTS` — breakeven bps, not an assumed cost.
2. `Gate.DSR` reading `N` from the ledger. This is the headline claim; it needs
   at least two completed trials in the family, so run the parameter variants
   you were going to run anyway and *record every one*.
3. `signals/embeddings.py` — the same economic claim, sentence embeddings
   instead of TF-IDF, put through the identical gauntlet. The comparison is the
   research question: does the embedding formulation buy anything that survives
   an honest deflation?
4. `Gate.INTEGRITY` — Isolation Forest on the panel. This is your edge; nobody
   else replicating a text signal will do it.
5. `Gate.PBO` — CSCV.

---

## Rules that make this repo different from every other junior backtest

1. **No number in the README that did not come out of the gauntlet.**
2. **Every variant is recorded before it is run**, including the ones you
   abandon. The abandoned ones are what make the DSR honest.
3. **A gate that is not implemented raises.** It never silently passes.
4. **Public data only.** No employer data, no vendor data, no internal models.
   Check the external-publication policy before the repo goes public.
5. **Report where signals die, not just which survive.** The failures are the
   contribution.
