"""Build the filing corpus. Run this first — it takes the longest.

    python -m corpus.fetch --top-n 200 --start 2012-01-01 --end 2025-12-31

Resumable: everything is cached by accession number, so a re-run after an
interruption downloads only what is missing. The index parquet is rewritten
each run from the cache, so it always describes what is actually on disk.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters import quant_lake  # noqa: E402
from corpus.edgar import EdgarClient, Filing  # noqa: E402
from referee import runlog  # noqa: E402

INDEX_PATH = Path(__file__).resolve().parent / "filings_index.parquet"


def build(
    *,
    top_n: int,
    start: str,
    end: str,
    forms: tuple[str, ...],
    index_name: str | None,
    text: bool,
) -> pd.DataFrame:
    tickers = quant_lake.liquid_universe(
        start=start, end=end, top_n=top_n, index_name=index_name
    )
    print(f"universe: {len(tickers)} names by median dollar ADV {start}..{end}")

    client = EdgarClient()
    mapping = client.ticker_to_cik()

    rows: list[dict] = []
    unresolved: list[str] = []
    for i, ticker in enumerate(tickers, 1):
        cik = mapping.get(ticker.upper())
        if cik is None:
            unresolved.append(ticker)
            continue
        try:
            filings = client.filings(ticker, cik, forms=forms)
        except Exception as exc:  # noqa: BLE001
            print(f"  [{i}/{len(tickers)}] {ticker}: index failed — {exc}")
            continue
        keep = [
            f for f in filings if start <= f.acceptance_datetime[:10] <= end
        ]
        rows.extend(asdict(f) for f in keep)
        print(f"  [{i}/{len(tickers)}] {ticker}: {len(keep)} filings", flush=True)

    if unresolved:
        # Named, not swallowed. A ticker that silently resolves to nothing
        # shrinks the sample in a way that is invisible in the final table.
        print(f"\nunresolved tickers ({len(unresolved)}): {unresolved}")

    index = pd.DataFrame(rows)
    if index.empty:
        raise SystemExit("no filings found — check the universe and date range")
    index["acceptance_datetime"] = pd.to_datetime(index["acceptance_datetime"])
    index = index.sort_values(["ticker", "acceptance_datetime"]).reset_index(drop=True)
    index.to_parquet(INDEX_PATH)
    print(f"\nindex: {len(index)} filings, {index['ticker'].nunique()} firms -> {INDEX_PATH}")

    if text:
        # One document per accession. GOOG and GOOGL share Alphabet's filing,
        # so iterating the index directly would fetch and parse it twice.
        docs = index.drop_duplicates("accession")
        print(f"\ndownloading {len(docs)} documents (cached by accession)...")
        done = failed = 0
        for row in docs.itertuples():
            f = Filing(
                cik=row.cik, ticker=row.ticker, form=row.form,
                accession=row.accession, period_end=row.period_end,
                filing_date=row.filing_date,
                acceptance_datetime=str(row.acceptance_datetime),
                primary_document=row.primary_document,
            )
            try:
                client.text(f)
                done += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"  {row.ticker} {row.accession}: {exc}")
            if done % 100 == 0 and done:
                print(f"  {done}/{len(docs)} documents", flush=True)
        print(f"\ndocuments: {done} ok, {failed} failed")

    return index


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--top-n", type=int, default=200)
    p.add_argument("--start", default="2012-01-01")
    p.add_argument("--end", default="2025-12-31")
    p.add_argument("--forms", default="10-K")
    p.add_argument("--index-name", default="sp500")
    p.add_argument("--no-text", action="store_true", help="build the index only")
    a = p.parse_args()
    with runlog.run(
        "corpus.fetch",
        top_n=a.top_n, start=a.start, end=a.end,
        forms=a.forms, index_name=a.index_name, text=not a.no_text,
    ) as rec:
        index = build(
            top_n=a.top_n,
            start=a.start,
            end=a.end,
            forms=tuple(x.strip() for x in a.forms.split(",")),
            index_name=a.index_name or None,
            text=not a.no_text,
        )
        rec.note(
            f"{len(index)} index rows, {index['accession'].nunique()} unique "
            f"accessions, {index['ticker'].nunique()} firms"
        )
        rec.output(INDEX_PATH)


if __name__ == "__main__":
    main()
