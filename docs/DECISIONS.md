# Decision log

Append-only, newest last. One entry per decision that a reader of the results
would otherwise have to reverse-engineer from the code. If a decision is later
reversed, add a new entry saying so — never edit or delete the old one, because
the sequence of what we believed and when is itself part of the audit trail.

Machine-written execution records live in `logs/INDEX.md`. Pre-registered
hypotheses live in the trial ledger. This file is for judgement calls.

Template:

    ## YYYY-MM-DD — short title
    **Decision.** What we chose.
    **Why.** The reasoning, including what we gave up.
    **Evidence.** Numbers, if any.
    **Reversible?** What it would cost to change our minds.

---

## 2026-09-06 — Align on `acceptanceDateTime`, never `filingDate` or period end
**Decision.** Every filing row carries EDGAR's `acceptanceDateTime`, and the
point-in-time gate audits against that field alone.
**Why.** `filingDate` is a date with no time and is occasionally a day late;
fiscal period end sits two to three months before the document existed. For an
annual-frequency text signal, aligning on period end is not a small bias — it
is plausibly most of the reported edge.
**Reversible?** No. Dropping the field would mean re-fetching the whole index.

## 2026-09-06 — Universe is top 200 by dollar ADV, 2012–2025, not the full S&P 500
**Decision.** ~200 names, ~2,500 10-Ks, rather than the full index back to 2005
(~9,000 filings).
**Why.** Scope. The full history is a weekend of downloading; the harness is
what is being built first, and it is indifferent to sample size.
**Reversible?** Yes, cheaply — the fetch is resumable and caches by accession.

## 2026-09-06 — Cross-check index membership against `quoteType == "EQUITY"`
**Decision.** `liquid_universe` requires a name to be an equity *and* to have
membership overlapping the study window.
**Why.** `index_membership.parquet` records GLD as an S&P 500 member from
1996-01-02 to 1997-05-05. GLD did not list until 2004, so that row is a
reused-ticker collision. Taken at face value it put a gold ETF in the top 20 by
liquidity.
**Evidence.** One bad row moved the universe. This is the project thesis in
miniature: a universe bug manufactures alpha, and no amount of model quality
catches it downstream.
**Reversible?** Yes, but there is no reason to.

## 2026-09-09 — Corpus downloaded; 11 tickers unresolved, 3 returned zero filings
**Decision.** Proceed with 2,474 unique filings across 186 firms rather than
chase the gaps now, and carry the gaps as a stated caveat.
**Why.** The unresolved names (TWTR, ATVI, ANTM, EA, WBA, PXD, X, FI, MRO, BK,
HES) are mostly delisted or renamed, so ticker-to-CIK lookup on the *current*
company_tickers.json misses them. That is a survivorship hole, and it leans the
sample toward firms that still exist in 2026. XOM, SE and PSKY resolved but
returned zero filings, which is a separate and unexplained bug.
**Evidence.** Coverage is otherwise even: 159–186 filings per year, no gaps.
**Reversible?** Yes. Fixing it means resolving historical tickers through the
former-names block in the submissions JSON. Worth doing before any result is
published; not worth blocking the first signal on.

## 2026-09-09 — Replace the regex HTML strip with a real parser (lxml), and cache raw HTML
**Decision.** Parse filings with `lxml.html` in `corpus/parse.py`, explicitly
dropping non-rendered inline-XBRL content; cache the raw HTML gzipped so the
text can be re-derived without re-downloading. Text cache is versioned by
parser version.
**Why.** The regex strip in `corpus/edgar.py` kept everything between tags,
including `ix:hidden` and `ix:header` blocks that no reader ever sees. More
importantly the old client cached only the *derived text* and discarded the
HTML, which made any parser change cost a full re-download — the corpus was one
decision away from being unreproducible.
**Evidence.** iXBRL hidden-fact pollution by filing year, measured on the
cached corpus: 0% of filings 2012–2020, 8.7% in 2021, 81.6% in 2022, 89.1% in
2023, 94.6% in 2024, 95.7% in 2025. Because the contamination arrives on a
calendar schedule and hits every firm at once, a year-over-year document
similarity signal would read the iXBRL mandate as a synchronized drop in
similarity across the entire universe — a factor that looks like news and is
actually a filing-format change.
**Reversible?** The parser is, cheaply, now that raw HTML is cached. Not
caching the HTML was not reversible, which is why it is fixed first.

## 2026-09-09 — Section extraction pairs each end with its *nearest preceding* start
**Decision.** In `signals/sections.py`, candidate section boundaries are paired
end-first: for each candidate terminator, take the nearest start above it, then
keep the longest of those spans.
**Why.** The obvious rule — maximise span over all start/end combinations —
pairs the *table of contents* occurrence of "Item 7" with the *body*
occurrence of "Item 7A" and returns everything in between.
**Evidence.** Measured on 200 sampled filings, the naive rule reported a 9.0%
extraction failure rate and a median "MD&A + risk factors" of **302,147
characters** — most of the filing. The corrected rule reports 14.0% failures and
a median of 140,151 characters. The failure rate went *up* because the bug was
manufacturing false successes.
**Reversible?** Yes. The 14% failure rate is a stated caveat and is worth
attacking later; it must never be reduced by falling back to the full document.

## 2026-09-09 — Term-count cosine, not corpus-wide TF-IDF
**Decision.** Default similarity is cosine on term counts over the two-document
vocabulary. `weighting="tfidf"` exists but fits IDF on an expanding window of
strictly prior filings, refit annually.
**Why.** Fitting TF-IDF on the whole corpus computes each term's inverse
document frequency from filings that had not happened yet. It is a genuine
lookahead that no date-based audit will catch, because it lives inside a
vectoriser rather than in a timestamp. Term-count cosine depends on nothing
outside the pair and is also what the paper does.
**Reversible?** Yes, and the expanding-window variant is a legitimate trial —
recorded in the ledger like any other.

## 2026-09-09 — The PIT gate executes at the session close, in exchange time
**Decision.** `referee/pit.py` reads a naive `signal_date` as a trading date in
`America/New_York` and compares acceptance against that date's **16:00 close**.
It reports `n_impossible` (gap < 0) separately from `n_lookahead` (gap <
embargo).
**Why.** `signal_date` is a date; `acceptanceDateTime` is an instant. Comparing
them requires committing to when in the session the trade happens, and that
choice is worth up to a full session of apparent gap. Leaving it implicit meant
the gate crashed on tz-aware input rather than answering. Reading a trading date
as UTC instead of exchange time would shift every date five hours and silently
change the violation count.
**Evidence.** The boundary case: a filing accepted 16:50 ET and traded at the
next close is 23h10m — real, but 0.97 days, so it breaches a one-day embargo.
The signal's alignment therefore adds its embargo in *trading days* after
bumping an after-close filing to the following session.
**Reversible?** The execution convention is a parameter. Changing it changes
every gap in the audit, so it is stated in the README rather than buried.

## 2026-09-09 — First result: naive alignment looks ahead on 100% of rows
**Decision.** Publish the failing run alongside the fixed one, as the repo's
first result.
**Evidence.** 2,474 filings, 185 firms. Dating the signal at fiscal period end:
2,474/2,474 rows (100.0%) trade a document that did not exist, median 50 days of
foresight, worst case 389. One trading day after acceptance: 0 violations,
median gap +2 days.
**Why it matters.** This is not an exotic error. It is what you get by joining a
text signal to a fundamentals panel on `period_end` and never asking when the
document arrived.
