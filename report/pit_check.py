"""Gate 0, run twice: the careless alignment and the honest one.

    python -m report.pit_check

This is the first real result in the repo, and it is deliberately a *failure*
first. A replication that dates each 10-K signal at the fiscal period end — the
date the financial data describes — is trading on a document that does not
exist yet. Everyone knows this in the abstract. The number below is what it
costs in this sample.

Only dates are needed, so this runs off the filings index alone and does not
wait on text extraction. The frame it hands the gate has the same columns the
full Lazy Prices signal produces, and the gate cannot tell the difference —
which is the point: the gate audits alignment, not the signal.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters import quant_lake  # noqa: E402
from referee import pit, runlog  # noqa: E402
from signals.lazy_prices import DEFAULT_EMBARGO_DAYS, align_signal_dates  # noqa: E402

INDEX_PATH = Path(__file__).resolve().parents[1] / "corpus" / "filings_index.parquet"
OUT_PATH = Path(__file__).resolve().parent / "pit_check.md"


def aligned_frame(index: pd.DataFrame, alignment: str, calendar) -> pd.DataFrame:
    df = index.copy()
    df["acceptance_datetime"] = pd.to_datetime(df["acceptance_datetime"], utc=True)
    df["signal_date"] = align_signal_dates(
        df["acceptance_datetime"],
        alignment=alignment,
        period_end=df["period_end"],
        embargo_days=DEFAULT_EMBARGO_DAYS,
        calendar=calendar,
    )
    return df.dropna(subset=["signal_date"])


def main() -> None:
    with runlog.run("report.pit_check") as rec:
        index = pd.read_parquet(INDEX_PATH).drop_duplicates("accession")
        calendar = quant_lake.load_prices().index
        print(f"filings: {len(index)}  firms: {index['ticker'].nunique()}")

        rows = []
        for alignment, label in (
            ("period_end", "naive — signal dated at fiscal period end"),
            ("acceptance", "honest — one trading day after EDGAR acceptance"),
        ):
            frame = aligned_frame(index, alignment, calendar)
            stats = pit.audit(frame)
            step = pit.gate(None, type("S", (), {"aligned": frame})(), None)
            rows.append({"alignment": alignment, "label": label, **stats,
                         "passed": step.passed})
            print(f"\n{alignment}: {label}")
            print(f"  {'PASSED' if step.passed else 'FAILED'}  {step.detail}")

        table = pd.DataFrame(rows)
        naive, honest = table.iloc[0], table.iloc[1]
        summary = (
            f"{naive['pct_lookahead']:.1f}% of rows lookahead under the naive "
            f"alignment (median {abs(naive['median_gap_days']):.0f} days of "
            f"foresight), {honest['pct_lookahead']:.1f}% under the honest one"
        )
        print(f"\n{summary}")
        rec.note(summary)

        OUT_PATH.write_text(
            "# Gate 0 — point-in-time audit\n\n"
            f"Sample: {len(index)} 10-K filings, {index['ticker'].nunique()} firms, "
            f"{index['acceptance_datetime'].min():%Y-%m}–"
            f"{index['acceptance_datetime'].max():%Y-%m}.\n\n"
            + table[[
                "alignment", "n", "n_lookahead", "pct_lookahead",
                "median_gap_days", "min_gap_days", "passed",
            ]].to_markdown(index=False)
            + "\n\nThe naive alignment is what a careless replication does: it dates the\n"
              "signal at the fiscal period end, because that is the date the financial\n"
              "data describes. The document itself did not exist until EDGAR accepted\n"
              "it, a median of "
            f"{abs(naive['median_gap_days']):.0f} calendar days later.\n"
        )
        rec.output(OUT_PATH)
        print(f"\nwrote {OUT_PATH}")


if __name__ == "__main__":
    main()
