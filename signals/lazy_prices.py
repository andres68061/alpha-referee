"""Lazy Prices — Cohen, Malloy & Nguyen (2020), replicated under the referee.

The claim: firms mostly copy last year's 10-K forward. When they *don't* — when
the language of the MD&A and risk factors changes materially — something has
changed that the market underreacts to. Low year-over-year document similarity
is therefore a short signal, high similarity a long one.

What this module produces is the *aligned* frame, one row per (firm, filing):

    ticker, accession, acceptance_datetime, signal_date, score,
    extraction_failed, gap_days

`score` is the similarity to the firm's previous 10-K. `signal_date` is the
date a trader could have acted on it; `acceptance_datetime` is EDGAR ground
truth for when the document existed. The point-in-time gate compares the two,
which is why both are carried and why neither is derived from the other inside
the gate.

Two alignment modes exist on purpose:

* ``alignment="acceptance"`` — the honest one. Trade `embargo_days` trading
  days after EDGAR accepted the filing.
* ``alignment="period_end"`` — the careless replication: date the signal at the
  fiscal period end, which is where the *data* is from, ignoring that the
  document did not exist yet. This mode is kept so the PIT gate can be run
  against it and the lookahead measured rather than asserted.

A note on the weighting, which is a lookahead trap in its own right. Fitting
TF-IDF on the whole corpus computes each term's inverse document frequency from
documents that had not been filed yet. It is a small leak and an easy one to
miss, since it lives in a vectoriser rather than in a date. The default here is
therefore plain term-count cosine, which is what the paper uses and which
cannot leak. ``weighting="tfidf"`` is available and fits IDF on an expanding
window of strictly prior filings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer

from signals.sections import extract_all

Alignment = Literal["acceptance", "period_end"]
Weighting = Literal["count", "tfidf"]

#: Default sections. MD&A plus risk factors is the paper's headline pairing.
DEFAULT_SECTIONS: tuple[str, ...] = ("item_1a", "item_7")

#: Consecutive 10-Ks should be about a year apart. A pair far outside that is a
#: restatement, a transition-period filing or a gap in our corpus, and comparing
#: across it measures something other than one year of drift.
MIN_GAP_DAYS, MAX_GAP_DAYS = 250, 550

#: One full trading day between the filing hitting EDGAR and the trade.
DEFAULT_EMBARGO_DAYS = 1

_WORD = re.compile(r"[a-z]{2,}")


@dataclass
class LazyPricesSignal:
    """The aligned frame plus the provenance a scorecard has to report."""

    aligned: pd.DataFrame
    params: dict[str, Any]
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def extraction_failure_rate(self) -> float:
        if self.aligned.empty:
            return float("nan")
        return float(self.aligned["extraction_failed"].mean())

    def usable(self) -> pd.DataFrame:
        """Rows a backtest may use: extraction succeeded and the gap is sane."""
        df = self.aligned
        return df[~df["extraction_failed"] & df["gap_ok"]].copy()


# ---------------------------------------------------------------- similarity


def _tokenise(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def cosine(a: str, b: str) -> float:
    """Cosine similarity of two documents on shared term counts.

    Vocabulary is the union of just these two documents, so the number depends
    on nothing outside the pair — no corpus statistics, therefore no leak.
    """
    if not a.strip() or not b.strip():
        return float("nan")
    vec = CountVectorizer(analyzer=_tokenise)
    counts = vec.fit_transform([a, b]).astype(np.float64)
    norms = np.sqrt(np.asarray(counts.multiply(counts).sum(axis=1))).ravel()
    if not norms.all():
        return float("nan")
    return float((counts[0].multiply(counts[1]).sum()) / (norms[0] * norms[1]))


class _ExpandingIdf:
    """TF-IDF whose IDF is fitted only on filings that already existed.

    Refitted once per calendar year on every filing accepted strictly before
    that year began. Refitting per document would be more exact and roughly
    2,500x more expensive; the approximation is stated rather than hidden, and
    it never uses a future document.
    """

    def __init__(self) -> None:
        self._by_year: dict[int, TfidfVectorizer | None] = {}

    def fit_year(self, year: int, prior_docs: list[str]) -> None:
        if len(prior_docs) < 50:
            # Too thin to estimate document frequencies. Refuse rather than
            # fit a noisy IDF and pretend it is the same estimator.
            self._by_year[year] = None
            return
        vec = TfidfVectorizer(analyzer=_tokenise, min_df=5)
        vec.fit(prior_docs)
        self._by_year[year] = vec

    def similarity(self, year: int, a: str, b: str) -> float:
        vec = self._by_year.get(year)
        if vec is None:
            return float("nan")
        m = vec.transform([a, b])
        norms = np.sqrt(np.asarray(m.multiply(m).sum(axis=1))).ravel()
        if not norms.all():
            return float("nan")
        return float(m[0].multiply(m[1]).sum() / (norms[0] * norms[1]))


# ---------------------------------------------------------------- alignment


def _trading_days() -> pd.DatetimeIndex:
    from adapters import quant_lake

    return quant_lake.load_prices().index


def align_signal_dates(
    acceptance: pd.Series,
    *,
    alignment: Alignment,
    period_end: pd.Series,
    embargo_days: int,
    calendar: pd.DatetimeIndex | None = None,
) -> pd.Series:
    """Map filings to the date the signal is treated as tradeable."""
    if alignment == "period_end":
        # Deliberately wrong. See the module docstring.
        return pd.to_datetime(period_end)
    if alignment != "acceptance":
        raise ValueError(f"unknown alignment {alignment!r}")

    cal = calendar if calendar is not None else _trading_days()
    cal = pd.DatetimeIndex(cal).tz_localize(None).sort_values()

    # Drop the timezone only after using it: a filing accepted 18:05 ET is a
    # next-day event, and truncating to a date first would lose that.
    accepted = pd.to_datetime(acceptance, utc=True).dt.tz_convert("America/New_York")
    same_day_cutoff = accepted.dt.normalize().dt.tz_localize(None)
    after_close = accepted.dt.hour >= 16
    effective = same_day_cutoff.where(~after_close, same_day_cutoff + pd.Timedelta(days=1))

    positions = cal.searchsorted(effective.to_numpy(), side="left") + embargo_days
    positions = np.clip(positions, 0, len(cal) - 1)
    out = pd.Series(cal[positions], index=acceptance.index)
    # A filing later than the last trading day we have prices for cannot be
    # traded at all; mark it rather than snapping it onto the final bar.
    out[effective > cal[-1]] = pd.NaT
    return out


# ---------------------------------------------------------------- build


def build(
    index: pd.DataFrame,
    *,
    text_loader: Callable[[str], str],
    sections: tuple[str, ...] = DEFAULT_SECTIONS,
    alignment: Alignment = "acceptance",
    weighting: Weighting = "count",
    embargo_days: int = DEFAULT_EMBARGO_DAYS,
    calendar: pd.DatetimeIndex | None = None,
    progress: bool = False,
) -> LazyPricesSignal:
    """Build the aligned Lazy Prices frame from a filings index.

    Args:
        index: filings index, one row per (ticker, filing), carrying
            ``ticker, accession, period_end, acceptance_datetime``.
        text_loader: accession -> filing text. Injected so the corpus cache,
            a test fixture and a future parser version are interchangeable.

    Returns:
        A `LazyPricesSignal`. Every filing in the index appears in the frame,
        including the ones whose section extraction failed — dropping them here
        would hide the failure rate from the scorecard.
    """
    df = index.copy()
    df["acceptance_datetime"] = pd.to_datetime(df["acceptance_datetime"], utc=True)
    df = df.sort_values(["ticker", "acceptance_datetime"]).reset_index(drop=True)

    # Extract once per document, not once per (ticker, filing) pair: GOOG and
    # GOOGL share Alphabet's accession, and parsing a 10-K is not cheap.
    bodies: dict[str, tuple[str, bool, str]] = {}
    for i, accession in enumerate(df["accession"].unique(), 1):
        try:
            text = text_loader(accession)
        except Exception as exc:  # noqa: BLE001
            bodies[accession] = ("", True, f"text unavailable: {exc}")
            continue
        bodies[accession] = extract_all(text, sections)
        if progress and i % 250 == 0:
            print(f"  extracted {i}/{df['accession'].nunique()} documents", flush=True)

    df["body"] = df["accession"].map(lambda a: bodies[a][0])
    df["section_failed"] = df["accession"].map(lambda a: bodies[a][1])
    df["failure_reason"] = df["accession"].map(lambda a: bodies[a][2])

    df["prev_body"] = df.groupby("ticker")["body"].shift(1)
    df["prev_failed"] = df.groupby("ticker")["section_failed"].shift(1)
    df["prev_accession"] = df.groupby("ticker")["accession"].shift(1)
    prev_accept = df.groupby("ticker")["acceptance_datetime"].shift(1)
    df["gap_days"] = (df["acceptance_datetime"] - prev_accept).dt.days

    idf = None
    if weighting == "tfidf":
        idf = _ExpandingIdf()
        df["idf_year"] = df["acceptance_datetime"].dt.year
        for year in sorted(df["idf_year"].unique()):
            prior = df.loc[
                (df["idf_year"] < year) & ~df["section_failed"], "body"
            ].tolist()
            idf.fit_year(int(year), prior)

    scores = []
    for row in df.itertuples():
        if row.prev_body is None or (isinstance(row.prev_body, float) and pd.isna(row.prev_body)):
            scores.append(float("nan"))
        elif row.section_failed or row.prev_failed:
            scores.append(float("nan"))
        elif idf is not None:
            scores.append(idf.similarity(int(row.idf_year), row.body, row.prev_body))
        else:
            scores.append(cosine(row.body, row.prev_body))
    df["score"] = scores

    df["signal_date"] = align_signal_dates(
        df["acceptance_datetime"],
        alignment=alignment,
        period_end=df["period_end"],
        embargo_days=embargo_days,
        calendar=calendar,
    )

    # A row is unusable if either filing in the pair failed extraction, if there
    # is no prior filing, or if the score could not be computed at all.
    df["extraction_failed"] = (
        df["section_failed"].fillna(True).astype(bool)
        | df["prev_failed"].fillna(True).astype(bool)
        | df["score"].isna()
    )
    df["gap_ok"] = df["gap_days"].between(MIN_GAP_DAYS, MAX_GAP_DAYS)

    aligned = df[[
        "ticker", "accession", "prev_accession", "period_end",
        "acceptance_datetime", "signal_date", "score",
        "extraction_failed", "failure_reason", "gap_days", "gap_ok",
    ]].copy()

    diagnostics = {
        "n_filings": int(len(df)),
        "n_documents": int(df["accession"].nunique()),
        "n_first_filing_no_prior": int(df["prev_accession"].isna().sum()),
        "section_failure_rate": float(df["section_failed"].mean()),
        "pair_failure_rate": float(df["extraction_failed"].mean()),
        "gap_rejected": int((~df["gap_ok"]).sum()),
        "n_usable": int((~df["extraction_failed"] & df["gap_ok"]).sum()),
        "score_mean": float(df["score"].mean(skipna=True)),
        "score_std": float(df["score"].std(skipna=True)),
    }
    params = {
        "sections": list(sections),
        "alignment": alignment,
        "weighting": weighting,
        "embargo_days": embargo_days,
        "min_gap_days": MIN_GAP_DAYS,
        "max_gap_days": MAX_GAP_DAYS,
    }
    return LazyPricesSignal(aligned=aligned, params=params, diagnostics=diagnostics)


def cache_text_loader(text_dir: str | Path) -> Callable[[str], str]:
    """Read extracted text out of the corpus cache by accession."""
    directory = Path(text_dir)

    def load(accession: str) -> str:
        path = directory / f"{accession}.txt"
        if not path.exists():
            raise FileNotFoundError(path)
        return path.read_text(errors="ignore")

    return load
