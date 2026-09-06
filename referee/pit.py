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
    gap = (
        pd.to_datetime(aligned[signal_date_col])
        - pd.to_datetime(aligned[acceptance_col])
    ).dt.total_seconds() / 86400.0

    violations = gap < embargo_days
    return {
        "n": int(len(gap)),
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
            f"{stats['n_lookahead']}/{stats['n']} rows use text before it was public "
            f"({stats['pct_lookahead']:.1f}%); median gap "
            f"{stats['median_gap_days']:.0f}d, min {stats['min_gap_days']:.0f}d"
        ),
    )
