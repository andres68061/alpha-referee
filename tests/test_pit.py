"""Gate 0 must be exact about *when*, including across timezones."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from referee import pit  # noqa: E402


def _frame(signal_dates, acceptances):
    return pd.DataFrame({
        "signal_date": pd.to_datetime(signal_dates),
        "acceptance_datetime": pd.to_datetime(acceptances, utc=True),
    })


def test_period_end_alignment_is_flagged_as_impossible():
    frame = _frame(["2022-12-31"], ["2023-02-15 21:50:00+00:00"])
    stats = pit.audit(frame)
    assert stats["n_impossible"] == 1
    assert stats["pct_lookahead"] == 100.0
    assert stats["median_gap_days"] < 0


def test_next_session_close_clears_the_embargo():
    """Accepted 09:00 ET, traded at the next close: 1.3 days, not 0.6."""
    frame = _frame(["2023-02-16"], ["2023-02-15 14:00:00+00:00"])
    stats = pit.audit(frame)
    assert stats["n_lookahead"] == 0
    assert 1.0 < stats["median_gap_days"] < 1.5


def test_naive_signal_date_is_read_in_exchange_time_not_utc():
    """Reading a trading date as UTC shifts it five hours and changes the count."""
    frame = _frame(["2023-02-15"], ["2023-02-15 20:00:00+00:00"])  # 15:00 ET
    stats = pit.audit(frame)
    # 16:00 ET close is one hour after a 15:00 ET acceptance: real, but far
    # inside the embargo, so it must be flagged without being called impossible.
    assert stats["n_impossible"] == 0
    assert stats["n_lookahead"] == 1


def test_embargo_and_impossible_are_reported_separately():
    frame = _frame(
        ["2022-12-31", "2023-02-16", "2023-03-01"],
        ["2023-02-15 21:50:00+00:00", "2023-02-15 21:50:00+00:00",
         "2023-02-15 21:50:00+00:00"],
    )
    stats = pit.audit(frame)
    assert stats["n"] == 3
    assert stats["n_impossible"] == 1, "only the period-end row predates the filing"
    # The second row is the boundary case worth knowing about: accepted 16:50 ET
    # and traded at the *next* close is 23h10m — real, but 0.97 days, so it
    # breaches a one-day embargo. This is exactly why the signal's alignment
    # adds its embargo in trading days *after* bumping an after-close filing to
    # the following session, rather than trusting the raw next session.
    assert stats["n_lookahead"] == 2


def test_gate_fails_loudly_and_names_both_counts():
    frame = _frame(["2022-12-31"], ["2023-02-15 21:50:00+00:00"])
    step = pit.gate(None, type("S", (), {"aligned": frame})(), None)
    assert not step.passed
    assert "predate the filing entirely" in step.detail
