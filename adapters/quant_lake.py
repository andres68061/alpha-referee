"""Read-only adapter over the ``quant`` data lake.

Design rule: alpha-referee owns the filing corpus and the gauntlet. It owns no
price data. Prices, factor returns, liquidity and sector labels are read from
``quant/data`` and never written to. If that repo moves, one constant changes
here and nothing else in this project notices.

The lake, as of writing:

    data/factors/prices.parquet        wide, index=date, 8,911 symbol columns
    data/factors/dollar_adv_21d.parquet  same shape — 21d average dollar volume
    data/factors/fama_french_5.parquet   long, date + mkt_rf smb hml rmw cma rf
    data/universe/index_membership.parquet  symbol, index_name, valid_from, valid_to
    data/sectors/sector_classifications.parquet  symbol -> sector

Two things the lake does not have, which this module supplies itself:

  * the **momentum** factor (FF5 is five factors; UMD is a separate Ken French
    file). Fetched once and cached under ``data/`` here.
  * a **liquidity-ranked universe** that respects point-in-time index
    membership. Built here because the ranking window is a research choice and
    belongs with the research, not in the lake.
"""

from __future__ import annotations

import io
import os
import zipfile
from functools import lru_cache
from pathlib import Path

import pandas as pd
import requests

QUANT_ROOT = Path(os.environ.get("QUANT_ROOT", Path(__file__).resolve().parents[2] / "quant"))
LOCAL_DATA = Path(__file__).resolve().parents[1] / "data"

_PRICES = QUANT_ROOT / "data/factors/prices.parquet"
_ADV = QUANT_ROOT / "data/factors/dollar_adv_21d.parquet"
_FF5 = QUANT_ROOT / "data/factors/fama_french_5.parquet"
_MEMBERSHIP = QUANT_ROOT / "data/universe/index_membership.parquet"
_SECTORS = QUANT_ROOT / "data/sectors/sector_classifications.parquet"

_KEN_FRENCH_MOM = (
    "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
    "F-F_Momentum_Factor_daily_CSV.zip"
)


class LakeMissing(FileNotFoundError):
    """The quant lake is not where we expected it.

    Raised loudly rather than falling back to synthetic data. A gauntlet run on
    invented prices would produce a scorecard that looks exactly like a real one.
    """


def _require(path: Path) -> Path:
    if not path.exists():
        raise LakeMissing(
            f"{path} not found. Set QUANT_ROOT to the quant repo, "
            f"currently resolved to {QUANT_ROOT}"
        )
    return path


# ---------------------------------------------------------------- prices


@lru_cache(maxsize=1)
def _prices_raw() -> pd.DataFrame:
    df = pd.read_parquet(_require(_PRICES))
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df.sort_index()


def load_prices(
    symbols: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Wide adjusted close panel, index=date (tz-naive), columns=symbol."""
    df = _prices_raw()
    if symbols is not None:
        keep = [s for s in symbols if s in df.columns]
        missing = set(symbols) - set(keep)
        if missing:
            raise KeyError(
                f"{len(missing)} symbols absent from the price panel, e.g. "
                f"{sorted(missing)[:5]}. Drop them from the universe explicitly "
                f"rather than letting them vanish silently."
            )
        df = df[keep]
    return df.loc[start:end]


def load_returns(
    symbols: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Simple daily returns.

    One extra day is loaded before ``start`` so the first in-sample return is a
    real return and not a NaN that quietly becomes a zero downstream.
    """
    pad = None if start is None else (pd.Timestamp(start) - pd.Timedelta(days=10)).date().isoformat()
    px = load_prices(symbols, pad, end)
    return px.pct_change().loc[start:end]


def load_dollar_adv(
    symbols: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    df = pd.read_parquet(_require(_ADV))
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df = df.sort_index()
    if symbols is not None:
        df = df[[s for s in symbols if s in df.columns]]
    return df.loc[start:end]


# ---------------------------------------------------------------- factors


def load_ff5(start: str | None = None, end: str | None = None) -> pd.DataFrame:
    """Daily FF5 + risk-free, index=date, already in decimal units.

    ``date`` round-trips as the pandas index in this parquet but appears as a
    column in the arrow schema, so accept either rather than assuming one.
    """
    df = pd.read_parquet(_require(_FF5))
    if "date" in df.columns:
        df = df.set_index("date")
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df.sort_index().loc[start:end]


def load_momentum(start: str | None = None, end: str | None = None) -> pd.Series:
    """Daily UMD from Ken French, cached locally on first call.

    Kept separate from FF5 because it is a separate file upstream and because
    conflating "FF5" with "FF5+MOM" in a results table is exactly the kind of
    quiet imprecision the orthogonalization gate exists to prevent.
    """
    cache = LOCAL_DATA / "ff_momentum_daily.parquet"
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        resp = requests.get(_KEN_FRENCH_MOM, timeout=60)
        resp.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            raw = zf.read(zf.namelist()[0]).decode("latin-1")
        rows = []
        for line in raw.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) == 2 and parts[0].isdigit() and len(parts[0]) == 8:
                rows.append((parts[0], float(parts[1]) / 100.0))
        if not rows:
            raise ValueError("could not parse the Ken French momentum file")
        out = pd.DataFrame(rows, columns=["date", "mom"])
        out["date"] = pd.to_datetime(out["date"], format="%Y%m%d")
        out.set_index("date").to_parquet(cache)
    return pd.read_parquet(cache)["mom"].loc[start:end]


def load_factors(start: str | None = None, end: str | None = None) -> pd.DataFrame:
    """FF5 + MOM on one index. The orthogonalization gate's right-hand side."""
    ff5 = load_ff5(start, end)
    mom = load_momentum(start, end)
    return ff5.join(mom, how="inner")


# ---------------------------------------------------------------- universe


@lru_cache(maxsize=1)
def _membership() -> pd.DataFrame:
    df = pd.read_parquet(_require(_MEMBERSHIP))
    for col in ("valid_from", "valid_to"):
        df[col] = pd.to_datetime(df[col]).dt.tz_localize(None)
    return df


def members_on(date, index_name: str = "sp500") -> set[str]:
    """Index constituents as of a date. Survivorship-free by construction."""
    ts = pd.Timestamp(date).tz_localize(None) if pd.Timestamp(date).tzinfo else pd.Timestamp(date)
    df = _membership()
    df = df[df["index_name"] == index_name]
    live = (df["valid_from"] <= ts) & (df["valid_to"].isna() | (df["valid_to"] >= ts))
    return set(df.loc[live, "symbol"])


@lru_cache(maxsize=1)
def _classifications() -> pd.DataFrame:
    return pd.read_parquet(_require(_SECTORS))


def load_sectors() -> pd.Series:
    return _classifications().set_index("symbol")["sector"]


def common_stocks() -> set[str]:
    """Symbols the classification file calls ordinary equity.

    Needed because index membership alone does not guarantee a common stock.
    ``index_membership.parquet`` records GLD as an S&P 500 member from
    1996-01-02 to 1997-05-05 — GLD did not list until 2004, so that row is a
    reused-ticker collision, and taking membership at face value puts a gold
    ETF in an equity universe. Cross-checking against the security type is the
    cheap guard, and the disagreement itself is worth reporting.
    """
    df = _classifications()
    return set(df.loc[df["quoteType"] == "EQUITY", "symbol"])


def liquid_universe(
    start: str,
    end: str,
    top_n: int = 200,
    index_name: str | None = "sp500",
) -> list[str]:
    """The ``top_n`` names by median 21-day dollar ADV over the sample.

    Deliberately NOT point-in-time: this picks one fixed name list for the whole
    study. That is a known, stated bias — the list tilts toward firms that were
    liquid over the full window — and it is the tradeoff taken to keep the EDGAR
    download to a few thousand filings. The gauntlet reports it as a caveat
    rather than hiding it; a point-in-time universe is a later upgrade, not a
    silent one.
    """
    adv = load_dollar_adv(start=start, end=end)
    if index_name:
        mem = _membership()
        mem = mem[mem["index_name"] == index_name]
        # Membership must overlap the study window, not merely have existed at
        # some point in history. "Ever a member" drags in names that left the
        # index decades before the sample starts.
        overlaps = (mem["valid_from"] <= pd.Timestamp(end)) & (
            mem["valid_to"].isna() | (mem["valid_to"] >= pd.Timestamp(start))
        )
        in_window = set(mem.loc[overlaps, "symbol"]) & common_stocks()
        adv = adv[[c for c in adv.columns if c in in_window]]
    px = _prices_raw().loc[start:end]
    coverage = px.notna().mean()
    eligible = coverage[coverage > 0.5].index
    adv = adv[[c for c in adv.columns if c in eligible]]
    ranked = adv.median(skipna=True).dropna().sort_values(ascending=False)
    return list(ranked.head(top_n).index)
