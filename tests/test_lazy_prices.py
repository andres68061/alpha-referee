"""The signal's two failure modes: silent extraction fallback, and lookahead."""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from signals import lazy_prices as lp  # noqa: E402
from signals.sections import extract, extract_all  # noqa: E402

BOILERPLATE = "the company operates in a competitive industry " * 400


def _filing(mdna: str, risk: str = "we face risks from competition " * 200) -> str:
    """A 10-K with a table of contents, as every real one has."""
    return "\n".join([
        "TABLE OF CONTENTS",
        "Item 1A. Risk Factors 12",
        "Item 1B. Unresolved Staff Comments 20",
        "Item 7. Management's Discussion 30",
        "Item 7A. Quantitative Disclosures 55",
        "Item 8. Financial Statements 60",
        "",
        "Item 1A. Risk Factors",
        risk,
        "Item 1B. Unresolved Staff Comments",
        "None.",
        "Item 7. Management's Discussion",
        mdna,
        "Item 7A. Quantitative Disclosures",
        "Not applicable.",
    ])


def test_table_of_contents_is_not_mistaken_for_the_section():
    section = extract(_filing(BOILERPLATE), "item_7")
    assert not section.failed
    assert section.text.startswith("Management's Discussion")
    assert "Financial Statements 60" not in section.text


def test_section_does_not_run_from_toc_start_to_body_end():
    """The bug that produced a 302k-character 'MD&A' on the real corpus."""
    section = extract(_filing(BOILERPLATE), "item_7")
    assert "TABLE OF CONTENTS" not in section.text
    assert "Risk Factors" not in section.text


def test_missing_section_fails_loudly_rather_than_returning_the_document():
    text = "Item 1. Business\n" + BOILERPLATE
    body, failed, reason = extract_all(text, ("item_1a", "item_7"))
    assert failed
    assert "item_1a" in reason
    assert len(body) < len(text)


def test_identical_filings_score_one_and_rewrites_score_lower():
    same = lp.cosine(BOILERPLATE, BOILERPLATE)
    different = lp.cosine(BOILERPLATE, "an entirely new discussion of novel matters " * 400)
    assert same == pytest.approx(1.0)
    assert different < same


def test_naive_alignment_is_detectably_before_the_filing_exists():
    """`period_end` mode must produce the lookahead the PIT gate is built to catch."""
    acceptance = pd.Series(pd.to_datetime(["2023-02-15 21:50:00+00:00"]))
    period_end = pd.Series(["2022-12-31"])
    naive = lp.align_signal_dates(
        acceptance, alignment="period_end", period_end=period_end, embargo_days=1
    )
    assert naive.iloc[0] < acceptance.dt.tz_localize(None).iloc[0]


def test_acceptance_alignment_lands_after_the_filing_and_after_an_evening_filing():
    calendar = pd.DatetimeIndex(pd.bdate_range("2023-01-01", "2023-03-31"))
    acceptance = pd.Series(pd.to_datetime([
        "2023-02-15 14:00:00+00:00",  # 09:00 ET, during the session
        "2023-02-15 23:30:00+00:00",  # 18:30 ET, after the close
    ]))
    dates = lp.align_signal_dates(
        acceptance,
        alignment="acceptance",
        period_end=pd.Series(["2022-12-31", "2022-12-31"]),
        embargo_days=1,
        calendar=calendar,
    )
    assert dates.iloc[0] == pd.Timestamp("2023-02-16")
    # Filed after the close: the same-day bar was never available.
    assert dates.iloc[1] == pd.Timestamp("2023-02-17")


def test_build_keeps_failed_rows_so_the_failure_rate_is_visible():
    index = pd.DataFrame({
        "ticker": ["AAA", "AAA", "BBB", "BBB"],
        "accession": ["a1", "a2", "b1", "b2"],
        "period_end": ["2021-12-31", "2022-12-31", "2021-12-31", "2022-12-31"],
        "acceptance_datetime": pd.to_datetime([
            "2022-02-15 21:00:00+00:00", "2023-02-15 21:00:00+00:00",
            "2022-02-15 21:00:00+00:00", "2023-02-15 21:00:00+00:00",
        ]),
    })
    docs = {
        "a1": _filing(BOILERPLATE),
        "a2": _filing(BOILERPLATE),
        "b1": _filing(BOILERPLATE),
        "b2": "Item 1. Business\nno sections here",  # extraction must fail
    }
    calendar = pd.DatetimeIndex(pd.bdate_range("2021-01-01", "2023-12-31"))
    sig = lp.build(index, text_loader=docs.__getitem__, calendar=calendar)

    assert len(sig.aligned) == 4, "failed rows must not be dropped"
    bbb = sig.aligned.set_index("accession").loc["b2"]
    assert bool(bbb["extraction_failed"])
    aaa = sig.aligned.set_index("accession").loc["a2"]
    assert not bool(aaa["extraction_failed"])
    assert aaa["score"] == pytest.approx(1.0)
    assert sig.diagnostics["n_usable"] == 1
