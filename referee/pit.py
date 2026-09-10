"""Gate 0 — point-in-time audit.

The single most common way a published text signal fails to replicate is that
the researcher aligned filing content to the filing's *period end* rather than
to the moment the document became public. A 10-K for fiscal year ending
December is often not filed until late February. Using December's text to
trade December is not a small bias; for annual-frequency signals it is most of
the reported edge.

This gate is deliberately first, and deliberately mechanical: it compares the
timestamp the signal was aligned on against EDGAR's ``acceptanceDateTime``, and
reports the distribution of the gap. Any negative gap is a lookahead.
"""

from __future__ import annotations

import pandas as pd

from referee.verdict import Gate, Step

#: Filings become searchable on EDGAR the same session they are accepted, but a
#: signal that trades the same close is assuming an unrealistic reaction speed.
#: One full trading day is the conservative default.
DEFAULT_EMBARGO_DAYS = 1

#: ``signal_date`` is a trading *date*, not an instant. Comparing a date
#: against a timestamp requires committing to when in the session the trade
#: happens, and that choice is worth up to a full session of apparent gap — so
#: it is stated here rather than left to whatever timezone the frame arrived
#: with. The close is the conservative end of the range: it is the latest we
#: could have traded, and it is where a monthly-rebalanced decile book prices.
EXECUTION_TIME = "16:00"
EXECUTION_TZ = "America/New_York"


def _to_utc_instant(dates, *, at_close: bool) -> pd.Series:
    """Coerce dates or timestamps to tz-aware UTC instants.

    Naive values are read as wall-clock times in ``EXECUTION_TZ`` — a trading
    date is an exchange-local concept, and silently treating it as UTC would
    shift every date five hours and quietly change the lookahead count.
    """
    ts = pd.to_datetime(dates)
    if at_close and getattr(ts.dt, "tz", None) is None and (ts.dt.time == pd.Timestamp("00:00").time()).all():
        ts = ts.dt.normalize() + pd.Timedelta(EXECUTION_TIME + ":00")
    if getattr(ts.dt, "tz", None) is None:
        ts = ts.dt.tz_localize(EXECUTION_TZ, nonexistent="shift_forward", ambiguous=True)
    return ts.dt.tz_convert("UTC")


def audit(
    aligned: pd.DataFrame,
    *,
    signal_date_col: str = "signal_date",
    acceptance_col: str = "acceptance_datetime",
    embargo_days: int = DEFAULT_EMBARGO_DAYS,
) -> dict[str, float]:
    """Return the gap distribution between signal date and public availability.

    Args:
        aligned: one row per (firm, filing), carrying both timestamps.

    Returns:
        Summary with ``n_lookahead`` (rows the signal could not have known),
        ``pct_lookahead``, and the median gap in calendar days.
    """
    traded = _to_utc_instant(aligned[signal_date_col], at_close=True)
    public = _to_utc_instant(aligned[acceptance_col], at_close=False)
    gap = (traded - public).dt.total_seconds() / 86400.0

    # Two distinct failures, reported separately: trading a document that did
    # not exist (impossible), and trading one that existed but not long enough
    # to have been read (implausible). Collapsing them hides which one it is.
    impossible = gap < 0
    violations = gap < embargo_days
    return {
        "n": int(len(gap)),
        "n_impossible": int(impossible.sum()),
        "n_lookahead": int(violations.sum()),
        "pct_lookahead": float(violations.mean() * 100.0),
        "median_gap_days": float(gap.median()),
        "min_gap_days": float(gap.min()),
    }


def gate(panel, signal, ctx) -> Step:
    stats = audit(signal.aligned)
    clean = stats["n_lookahead"] == 0
    return Step(
        gate=Gate.PIT,
        sharpe=None,
        passed=clean,
        detail=(
            f"{stats['n_lookahead']}/{stats['n']} rows breach the embargo "
            f"({stats['pct_lookahead']:.1f}%), of which {stats['n_impossible']} "
            f"predate the filing entirely; median gap "
            f"{stats['median_gap_days']:.0f}d, min {stats['min_gap_days']:.0f}d"
        ),
    )
